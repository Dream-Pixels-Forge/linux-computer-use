"""Unit tests for the AT-SPI tree reader, using fake accessible objects."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from linux_computer_use.drivers import atspi
from linux_computer_use.drivers.atspi import ATSPIDriver, match_window


class FakeAction:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.done: list[int] = []

    def get_n_actions(self) -> int:
        return len(self.names)

    def get_action_name(self, i: int) -> str:
        return self.names[i]

    def do_action(self, i: int) -> bool:
        self.done.append(i)
        return True


class FakeComponent:
    def __init__(self, rect: tuple[int, int, int, int]) -> None:
        self.rect = rect
        self.focused = False

    def get_extents(self, _coord: Any) -> SimpleNamespace:
        x, y, w, h = self.rect
        return SimpleNamespace(x=x, y=y, width=w, height=h)

    def grab_focus(self) -> bool:
        self.focused = True
        return True


class Node:
    def __init__(
        self,
        role: str,
        name: str = "",
        children: list[Node] | None = None,
        states: tuple[str, ...] = ("showing", "visible", "enabled", "sensitive"),
        rect: tuple[int, int, int, int] = (0, 0, 10, 10),
        actions: list[str] | None = None,
        pid: int = 0,
    ) -> None:
        self.role, self.name, self.kids, self.pid = role, name, children or [], pid
        self.states = states
        self.component = FakeComponent(rect)
        self.action = FakeAction(actions) if actions else None

    def get_role_name(self) -> str:
        return self.role

    def get_name(self) -> str:
        return self.name

    def get_description(self) -> str:
        return ""

    def get_accessible_id(self) -> str:
        return ""

    def get_process_id(self) -> int:
        return self.pid

    def get_child_count(self) -> int:
        return len(self.kids)

    def get_child_at_index(self, i: int) -> Node:
        return self.kids[i]

    def get_state_set(self) -> SimpleNamespace:
        return SimpleNamespace(
            get_states=lambda: [SimpleNamespace(value_nick=s) for s in self.states]
        )

    def get_component_iface(self) -> FakeComponent:
        return self.component

    def get_action_iface(self) -> FakeAction | None:
        return self.action

    def get_text_iface(self) -> SimpleNamespace | None:
        value = getattr(self, "value", None)
        if value is None:
            return None
        return SimpleNamespace(
            get_character_count=lambda: len(value),
            get_text=lambda start, end: value[start:end],
        )


class Broken(Node):
    """An app that died mid-walk: every call raises."""

    def __getattribute__(self, name: str) -> Any:
        if name.startswith("get_"):
            raise RuntimeError("org.freedesktop.DBus.Error.ServiceUnknown")
        return super().__getattribute__(name)


@pytest.fixture
def driver() -> ATSPIDriver:
    d = ATSPIDriver()
    d._tried = True
    d._atspi = SimpleNamespace(
        CoordType=SimpleNamespace(SCREEN=0),
        Text=SimpleNamespace(
            get_character_count=lambda n: n.get_text_iface().get_character_count(),
            get_text=lambda n, start, end: n.get_text_iface().get_text(start, end),
        ),
    )
    return d


def demo_window() -> Node:
    return Node("frame", "Demo", rect=(60, 60, 360, 260), children=[
        Node("filler", children=[
            Node("label", "Clicks: 0"),
            Node("text", states=("showing", "editable", "focusable", "enabled"), actions=["activate"]),
            Node("push button", "Count", actions=["click"], states=("showing", "focused")),
            Node("menu", "Hidden", states=("visible",), children=[Node("menu item", "Secret")]),
        ]),
    ])


def test_read_tree_flattens_visible_nodes(driver: ATSPIDriver) -> None:
    tree = driver.read_tree(demo_window(), window_id=7)
    assert [(e.index, e.role, e.name, e.parent_index) for e in tree.elements] == [
        (0, "frame", "Demo", -1),
        (1, "filler", "", 0),
        (2, "label", "Clicks: 0", 1),
        (3, "text", "", 1),
        (4, "push button", "Count", 1),
    ]
    assert tree.elements[1].children == [2, 3, 4]
    assert tree.elements[0].window_id == 7
    assert (tree.elements[0].x, tree.elements[0].width) == (60, 360)
    assert not tree.sensitive and not tree.truncated


def test_read_tree_reports_states_and_actions(driver: ATSPIDriver) -> None:
    tree = driver.read_tree(demo_window(), window_id=7)
    text, button = tree.elements[3], tree.elements[4]
    assert text.state == ["focusable", "editable"]
    assert text.actions == ["activate"]
    assert button.actions == ["click"]
    assert button.state == ["focused", "disabled"]  # no "sensitive"/"enabled" state


def test_markdown(driver: ATSPIDriver) -> None:
    markdown = driver.read_tree(demo_window(), window_id=7).to_markdown()
    assert markdown.splitlines() == [
        '- [0] frame "Demo"',
        "  - [1] filler",
        '    - [2] label "Clicks: 0"',
        "    - [3] text (activate) {focusable, editable}",
        '    - [4] push button "Count" (click) {focused, disabled}',
    ]


def test_editable_fields_report_value_but_passwords_do_not(driver: ATSPIDriver) -> None:
    name = Node("text", states=("showing", "editable"))
    name.value = "Ada"  # type: ignore[attr-defined]
    secret = Node("password text", states=("showing", "editable"))
    secret.value = "hunter2"  # type: ignore[attr-defined]
    label = Node("label", "Hi")
    label.value = "Hi"  # type: ignore[attr-defined]
    tree = driver.read_tree(Node("frame", children=[name, secret, label]), window_id=1)
    assert [e.value for e in tree.elements] == [None, "Ada", None, None]
    assert "= 'Ada'" in tree.to_markdown()
    assert "hunter2" not in tree.to_markdown()


def test_password_field_marks_tree_sensitive(driver: ATSPIDriver) -> None:
    window = Node("dialog", "Login", children=[Node("text", "User"), Node("password text", "Password")])
    tree = driver.read_tree(window, window_id=1)
    assert tree.sensitive
    assert tree.sensitive_reasons == ["password field [2]"]


def test_tree_is_truncated(driver: ATSPIDriver, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(atspi, "MAX_ELEMENTS", 3)
    window = Node("frame", children=[Node("list item", str(i)) for i in range(10)])
    tree = driver.read_tree(window, window_id=1)
    assert len(tree.elements) == 3
    assert tree.truncated
    assert tree.to_markdown().endswith("(tree truncated at 3 elements)")


def test_dead_nodes_are_skipped(driver: ATSPIDriver) -> None:
    window = Node("frame", "W", children=[Broken("x"), Node("push button", "OK")])
    tree = driver.read_tree(window, window_id=1)
    assert [e.name for e in tree.elements] == ["W", "OK"]


def test_click_action_preference(driver: ATSPIDriver) -> None:
    button = Node("push button", actions=["activate", "press"])
    assert driver.do_click_action(button)
    assert button.action is not None and button.action.done == [1]  # "press", not "activate"
    assert not driver.do_click_action(Node("text", actions=["activate"]))
    assert not driver.do_click_action(Node("label"))


def test_grab_focus(driver: ATSPIDriver) -> None:
    node = Node("text")
    assert driver.grab_focus(node)
    assert node.component.focused


def test_find_window_by_pid_and_title(driver: ATSPIDriver) -> None:
    wanted = Node("frame", "Doc 2", rect=(500, 0, 300, 300))
    apps = [
        Node("application", "other", pid=1, children=[Node("frame", "Doc 2")]),
        Node("application", "editor", pid=2, children=[
            Node("frame", "Doc 1", rect=(0, 0, 300, 300)), wanted,
        ]),
    ]
    driver._atspi.get_desktop = lambda _i: Node("desktop", children=apps)  # type: ignore[union-attr]
    assert driver.find_window(2, "Doc 2", (500, 0, 300, 300)) is wanted
    assert driver.find_window(3, "Doc 2", None) is None
    assert driver.find_window(0, "Doc 2", None) is None


def test_match_window_rules(driver: ATSPIDriver) -> None:
    a = Node("frame", "Same", rect=(0, 0, 100, 100))
    b = Node("frame", "Same", rect=(400, 400, 100, 100))
    c = Node("frame", "Other", rect=(800, 0, 100, 100))
    ext = driver.extents
    assert match_window([a, b, c], "Same", (400, 400, 100, 100), ext) is b  # title + position
    assert match_window([a, c], "Same", (999, 999, 1, 1), ext) is a  # title only
    assert match_window([a, c], "Renamed", (800, 0, 100, 100), ext) is c  # position only
    assert match_window([c], "Renamed", None, ext) is c  # only window
    assert match_window([a, c], "Renamed", None, ext) is None  # ambiguous


def test_unavailable_without_pygobject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(atspi, "_load_atspi", lambda: None)
    d = ATSPIDriver()
    assert not d.available
    assert d.find_window(123, "x", None) is None
