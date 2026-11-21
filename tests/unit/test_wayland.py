"""Unit tests for the AT-SPI-only Wayland driver and driver selection."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from linux_computer_use.drivers.base import NotSupportedError
from linux_computer_use.drivers.wayland import WaylandDriver
from linux_computer_use.mcp import server

from tests.unit.test_atspi import SCREEN, WINDOW, App, FakeComponent, Node


class FakeEditable(Node):
    def __init__(self, value: str = "") -> None:
        super().__init__("text", states=("showing", "editable", "focusable"))
        self.value = value
        self.caret = len(value)

    def get_editable_text_iface(self) -> FakeEditable:
        return self


def text_api() -> SimpleNamespace:
    return SimpleNamespace(
        get_character_count=lambda n: len(n.value),
        get_caret_offset=lambda n: n.caret,
        get_text=lambda n, a, b: n.value[a:b],
    )


def editable_api() -> SimpleNamespace:
    def insert(node: FakeEditable, position: int, text: str, length: int) -> bool:
        node.value = node.value[:position] + text[:length] + node.value[position:]
        return True

    return SimpleNamespace(insert_text=insert)


def make_app(title: str, pid: int, path: str, *children: Node) -> tuple[Node, Node]:
    frame = Node("frame", title, rect=(0, 0, 400, 300), children=list(children))
    frame.component = FakeComponent((0, 0, 400, 300), window_rect=(0, 0, 400, 300))
    frame.path = path  # type: ignore[attr-defined]
    app = Node("application", "demo", pid=pid, children=[frame])
    frame.get_application = lambda: App("gtk", "3.24")  # type: ignore[attr-defined]
    return app, frame


@pytest.fixture
def desktop() -> dict[str, Any]:
    button = Node("push button", "Count", actions=["click"], rect=(10, 20, 80, 30))
    button.component = FakeComponent((10, 20, 80, 30), window_rect=(10, 20, 80, 30))
    entry = FakeEditable("Hi ")
    label = Node("label", "Clicks: 0")
    app, frame = make_app("Demo", 42, "/a11y/1", button, entry, label)
    other_app, _ = make_app("Other", 43, "/a11y/9")
    return {"apps": [app, other_app], "frame": frame, "button": button, "entry": entry}


@pytest.fixture
def driver(desktop: dict[str, Any]) -> WaylandDriver:
    d = WaylandDriver()
    d.atspi._tried = True
    d.atspi._atspi = SimpleNamespace(
        CoordType=SimpleNamespace(SCREEN=SCREEN, WINDOW=WINDOW),
        Text=text_api(),
        EditableText=editable_api(),
        get_desktop=lambda _i: Node("desktop", children=desktop["apps"]),
    )
    return d


def test_lists_showing_frames_with_stable_ids(driver: WaylandDriver, desktop: dict[str, Any]) -> None:
    windows = driver.list_windows()
    assert [(w.window_id, w.title, w.pid) for w in windows] == [(1, "Demo", 42), (2, "Other", 43)]
    assert (windows[0].x, windows[0].y, windows[0].width, windows[0].height) == (0, 0, 400, 300)
    assert [w.window_id for w in driver.list_windows()] == [1, 2]  # same ids again

    desktop["frame"].states = ("visible",)  # minimized / unmapped
    assert [w.title for w in driver.list_windows()] == ["Other"]
    assert driver.get_window(1) is None


def test_window_state_is_window_relative(driver: WaylandDriver) -> None:
    driver.list_windows()
    state = driver.get_window_state(1)
    assert state.source == "atspi"
    assert state.coordinates == "window"
    button = next(e for e in state.elements if e.name == "Count")
    assert (button.x, button.y) == (10, 20)
    assert driver.get_window_state(99).elements == []


def test_click_uses_the_accessible_action(driver: WaylandDriver, desktop: dict[str, Any]) -> None:
    driver.list_windows()
    state = driver.get_window_state(1)
    button = next(e for e in state.elements if e.name == "Count")
    assert driver.click(button)
    assert desktop["button"].action.done == [0]

    label = next(e for e in state.elements if e.role == "label")
    with pytest.raises(NotSupportedError, match="no accessible click action"):
        driver.click(label)


def test_type_text_inserts_at_the_caret(driver: WaylandDriver, desktop: dict[str, Any]) -> None:
    driver.list_windows()
    state = driver.get_window_state(1)
    entry = next(e for e in state.elements if "editable" in e.state)
    assert driver.type_text("Ada", entry)
    assert desktop["entry"].value == "Hi Ada"

    with pytest.raises(NotSupportedError, match="not an editable text field"):
        driver.type_text("x", next(e for e in state.elements if e.role == "label"))
    with pytest.raises(NotSupportedError, match="editable element"):
        driver.type_text("x", state.elements[0])


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("press_key", ("Return",)),
        ("click_coordinate", (1, 2)),
        ("focus_window", (1,)),
        ("screenshot_desktop", ()),
        ("screenshot_window", (1,)),
    ],
)
def test_input_and_capture_are_refused(driver: WaylandDriver, method: str, args: tuple) -> None:
    with pytest.raises(NotSupportedError, match=r"Wayland|portal"):
        getattr(driver, method)(*args)


def test_scroll_is_refused(driver: WaylandDriver) -> None:
    driver.list_windows()
    root = driver.get_window_state(1).elements[0]
    with pytest.raises(NotSupportedError, match="Scrolling"):
        driver.scroll("down", 3, root)


def test_resolve_and_sensitive(driver: WaylandDriver) -> None:
    driver.list_windows()
    driver.get_window_state(1)
    assert driver.resolve_element(1, 1).name == "Count"  # type: ignore[union-attr]
    assert driver.resolve_element(1, 99) is None
    assert driver.check_sensitive(1) == []  # no Collection: falls back to the walk


@pytest.mark.parametrize(
    ("env", "kind"),
    [
        ({}, "x11"),
        ({"DISPLAY": ":0"}, "x11"),
        ({"WAYLAND_DISPLAY": "wayland-0"}, "wayland"),
        ({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, "wayland"),  # XWayland present
        ({"XDG_SESSION_TYPE": "wayland"}, "wayland"),
        ({"WAYLAND_DISPLAY": "wayland-0", "LCU_DRIVER": "x11"}, "x11"),
        ({"LCU_DRIVER": "Wayland"}, "wayland"),
    ],
)
def test_driver_kind(env: dict[str, str], kind: str) -> None:
    assert server.driver_kind(env) == kind


def test_driver_kind_rejects_unknown_values() -> None:
    with pytest.raises(server.ToolError, match="LCU_DRIVER"):
        server.driver_kind({"LCU_DRIVER": "mir"})


async def test_unsupported_actions_reach_the_client_with_their_reason(tmp_path) -> None:
    """MCP hides the message of unexpected exceptions; NotSupportedError must not be one."""
    from mcp.client import Client

    class Refusing:
        def get_window(self, window_id: int) -> Any:
            return SimpleNamespace(x=0, y=0, width=100, height=100)

        def check_sensitive(self, window_id: int) -> list[str]:
            return []

        def focus_window(self, window_id: int) -> bool:
            raise NotSupportedError("Focusing a window needs portal input on Wayland.")

    server.set_driver(Refusing())  # type: ignore[arg-type]
    try:
        async with Client(server.mcp) as client:
            result = await client.call_tool("press_key", {"keys": "Return", "window_id": 1})
        assert result.is_error
        assert "needs portal input on Wayland" in result.content[0].text
    finally:
        server.set_driver(None)
