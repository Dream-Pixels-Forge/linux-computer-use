"""Wayland driver with portal input: focus gating, keysyms, screenshots.

The portal itself is faked here; tests/integration/test_portal_dbus.py runs
the real D-Bus client against a fake portal service.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from linux_computer_use.drivers import keysyms, portal, uinput
from linux_computer_use.drivers.base import NotSupportedError
from linux_computer_use.drivers.wayland import KEYBOARD_UNVERIFIED_ENV, WaylandDriver
from linux_computer_use.mcp import server
from PIL import Image as PILImage

from tests.unit.test_atspi import SCREEN, WINDOW, Node
from tests.unit.test_wayland import editable_api, make_app, text_api

ACTIVE = ("showing", "visible", "enabled", "sensitive", "active")
CTRL, SHIFT, RETURN = 0xFFE3, 0xFFE1, 0xFF0D


class FakeSession:
    def __init__(self) -> None:
        self.keys: list[tuple[int, bool]] = []
        self.on_key: Any = None

    def key(self, keysym: int, *, pressed: bool) -> None:
        self.keys.append((keysym, pressed))
        if self.on_key:
            self.on_key(len(self.keys))


class FakePortal:
    def __init__(self, shot: Path) -> None:
        self.session = FakeSession()
        self.opened = 0
        self.shot = shot

    def remote_desktop(self) -> FakeSession:
        self.opened += 1
        return self.session

    def pump(self) -> None:
        pass

    def screenshot(self) -> str:
        return str(self.shot)


@pytest.fixture(autouse=True)
def gnome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    monkeypatch.delenv(KEYBOARD_UNVERIFIED_ENV, raising=False)


@pytest.fixture
def frames() -> dict[str, Node]:
    entry = Node("text", "Name", states=("showing", "editable", "focusable"))
    app, frame = make_app("Demo", 42, "/a11y/1", entry)
    other_app, other = make_app("Other", 43, "/a11y/9")
    frame.states = ACTIVE
    return {"apps": [app, other_app], "demo": frame, "other": other}  # type: ignore[dict-item]


@pytest.fixture
def fake_portal(tmp_path: Path) -> FakePortal:
    shot = tmp_path / "shot.png"
    PILImage.new("RGB", (64, 48), "white").save(shot)
    return FakePortal(shot)


@pytest.fixture
def driver(frames: dict[str, Any], fake_portal: FakePortal) -> WaylandDriver:
    d = WaylandDriver(portal_client=fake_portal)  # type: ignore[arg-type]
    d.atspi._tried = True
    d.atspi._atspi = SimpleNamespace(
        CoordType=SimpleNamespace(SCREEN=SCREEN, WINDOW=WINDOW),
        Text=text_api(),
        EditableText=editable_api(),
        get_desktop=lambda _i: Node("desktop", children=frames["apps"]),
    )
    d.list_windows()
    return d


def window_element(driver: WaylandDriver, window_id: int) -> Any:
    return driver.get_window_state(window_id).elements[0]


# --------------------------------------------------------------------------- #
# Keysyms
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("Return", [RETURN]),
        ("ctrl+c", [CTRL, ord("c")]),
        ("Ctrl+Shift+T", [CTRL, SHIFT, ord("T")]),
        ("alt+F4", [0xFFE9, 0xFFC1]),
        ("ctrl++", [CTRL, ord("+")]),
        ("+", [ord("+")]),
        ("Page_Down", [0xFF56]),
        ("super", [0xFFEB]),
    ],
)
def test_parse_combo(keys: str, expected: list[int]) -> None:
    assert keysyms.parse_combo(keys) == expected


@pytest.mark.parametrize("keys", ["", "ctrl+", "c+ctrl", "Bogus", "ctrl++x"])
def test_parse_combo_rejects(keys: str) -> None:
    with pytest.raises(keysyms.KeyNameError):
        keysyms.parse_combo(keys)


def test_text_keysyms() -> None:
    assert keysyms.text_keysyms("aZ é\n€") == [
        ord("a"), ord("Z"), 0x20, 0xE9, RETURN, 0x01000000 | 0x20AC,
    ]
    with pytest.raises(keysyms.KeyNameError):
        keysyms.text_keysyms("\x07")


# --------------------------------------------------------------------------- #
# Keyboard through the portal
# --------------------------------------------------------------------------- #


def test_press_key_presses_in_order_and_releases_in_reverse(
    driver: WaylandDriver, fake_portal: FakePortal
) -> None:
    assert driver.press_key("ctrl+c")
    assert fake_portal.session.keys == [
        (CTRL, True), (ord("c"), True), (ord("c"), False), (CTRL, False),
    ]


def test_press_key_into_a_named_window_needs_it_focused(
    driver: WaylandDriver, fake_portal: FakePortal
) -> None:
    assert driver.focus_window(1)
    with pytest.raises(NotSupportedError, match=r"Window 2 doesn't have keyboard focus; window 1"):
        driver.focus_window(2)
    with pytest.raises(NotSupportedError, match="bring window 2 to the front"):
        driver.press_key("Return", window_element(driver, 2))
    assert fake_portal.opened == 0
    assert fake_portal.session.keys == []


@pytest.mark.parametrize("active", [(), ("demo", "other")])
def test_no_keys_unless_exactly_one_window_is_focused(
    driver: WaylandDriver, frames: dict[str, Any], fake_portal: FakePortal, active: tuple
) -> None:
    frames["demo"].states = ("showing", "visible")
    for name in active:
        frames[name].states = ACTIVE
    with pytest.raises(NotSupportedError, match=r"No window reports|all report focus"):
        driver.press_key("Return")
    assert driver.get_focused_window() is None
    assert fake_portal.opened == 0


def test_no_keys_into_a_password_window(
    driver: WaylandDriver, frames: dict[str, Any], fake_portal: FakePortal
) -> None:
    frames["demo"].kids.append(Node("password text", "Password"))
    with pytest.raises(NotSupportedError, match="password field"):
        driver.press_key("Return")
    assert fake_portal.session.keys == []


def test_keyboard_off_on_unverified_desktops(
    driver: WaylandDriver, fake_portal: FakePortal, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    with pytest.raises(NotSupportedError, match="switched off on KDE"):
        driver.press_key("Return")
    assert fake_portal.opened == 0
    monkeypatch.setenv(KEYBOARD_UNVERIFIED_ENV, "1")
    assert driver.press_key("Return")


def test_keyboard_needs_the_portal_opt_in(driver: WaylandDriver) -> None:
    driver.portal = None
    with pytest.raises(NotSupportedError, match=portal.ENABLE_ENV):
        driver.press_key("Return")
    with pytest.raises(NotSupportedError, match=portal.ENABLE_ENV):
        driver.focus_window(1)


def test_bad_key_names_are_refused_before_asking(
    driver: WaylandDriver, fake_portal: FakePortal
) -> None:
    with pytest.raises(NotSupportedError, match="Unknown key"):
        driver.press_key("Hyper_Q")
    assert fake_portal.opened == 0


def test_type_text_without_element_types_into_the_focused_window(
    driver: WaylandDriver, fake_portal: FakePortal
) -> None:
    assert driver.type_text("Hi", window_element(driver, 1))
    assert fake_portal.session.keys == [
        (ord("H"), True), (ord("H"), False), (ord("i"), True), (ord("i"), False),
    ]


def test_typing_stops_when_focus_moves(
    driver: WaylandDriver, frames: dict[str, Any], fake_portal: FakePortal
) -> None:
    def steal_focus(sent: int) -> None:
        if sent == 2:  # first character done
            frames["demo"].states = ("showing", "visible")
            frames["other"].states = ACTIVE

    fake_portal.session.on_key = steal_focus
    with pytest.raises(NotSupportedError, match="doesn't have keyboard focus"):
        driver.type_text("x" * 40, window_element(driver, 1))
    # Everything typed before the check is one chunk; nothing after it.
    assert len(fake_portal.session.keys) == 2 * 16


def test_editable_elements_still_use_accessible_insertion(
    driver: WaylandDriver, fake_portal: FakePortal
) -> None:
    state = driver.get_window_state(1)
    entry = next(e for e in state.elements if "editable" in e.state)
    with pytest.raises(NotSupportedError, match="not an editable"):
        driver.type_text("x", entry)  # plain Node has no EditableText iface
    assert fake_portal.session.keys == []


# --------------------------------------------------------------------------- #
# Screenshots
# --------------------------------------------------------------------------- #


def test_screenshot_desktop_uses_the_portal(driver: WaylandDriver, fake_portal: FakePortal) -> None:
    assert driver.screenshot_desktop() == str(fake_portal.shot)
    driver.portal = None
    with pytest.raises(NotSupportedError, match=portal.ENABLE_ENV):
        driver.screenshot_desktop()


def test_window_screenshots_are_refused(driver: WaylandDriver) -> None:
    with pytest.raises(NotSupportedError, match="position on screen"):
        driver.screenshot_window(1)


async def test_server_screenshots_on_wayland(driver: WaylandDriver, frames: dict[str, Any]) -> None:
    from mcp.client import Client

    server.set_driver(driver)  # type: ignore[arg-type]
    try:
        async with Client(server.mcp) as client:
            ok = await client.call_tool("screenshot_desktop", {})
            assert not ok.is_error, ok.content
            window = await client.call_tool("screenshot_window", {"window_id": 1})
            assert window.is_error
            assert "position on screen" in window.content[0].text

            frames["other"].kids.append(Node("password text", "Password"))
            refused = await client.call_tool("screenshot_desktop", {})
            assert refused.is_error
            assert "password field" in refused.content[0].text
    finally:
        server.set_driver(None)


# --------------------------------------------------------------------------- #
# Restore tokens
# --------------------------------------------------------------------------- #


def test_token_store_is_owner_only(tmp_path: Path) -> None:
    store = portal.TokenStore(tmp_path / "state" / "lcu" / "token")
    assert store.load() is None
    store.save("abc")
    assert store.load() == "abc"
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.path.parent.stat().st_mode & 0o777 == 0o700
    store.clear()
    store.clear()
    assert store.load() is None


def test_portal_is_opt_in() -> None:
    assert not portal.enabled({})
    assert portal.enabled({portal.ENABLE_ENV: "1"})
    assert not portal.enabled({portal.ENABLE_ENV: "0"})


# --------------------------------------------------------------------------- #
# Scrolling through scroll bar values (no pointer)
# --------------------------------------------------------------------------- #


class FakeBar(Node):
    def __init__(self, orientation: str, value: float = 0, high: float = 100,
                 increment: float = 0, *, obeys: bool = True) -> None:
        super().__init__("scroll bar", states=("showing", "visible", orientation))
        self.value, self.high, self.increment, self.obeys = value, high, increment, obeys

    def get_value_iface(self) -> FakeBar:
        return self

    def get_current_value(self) -> float:
        return self.value

    def get_minimum_value(self) -> float:
        return 0

    def get_maximum_value(self) -> float:
        return self.high

    def get_minimum_increment(self) -> float:
        return self.increment

    def set_current_value(self, v: float) -> bool:
        if self.obeys:
            self.value = v
        return self.obeys


def with_parents(node: Node, parent: Node | None = None) -> Node:
    node.get_parent = lambda: parent  # type: ignore[attr-defined]
    for kid in node.kids:
        with_parents(kid, node)
    return node


@pytest.fixture
def scrolled(driver: WaylandDriver, frames: dict[str, Any]) -> dict[str, Any]:
    rows = [Node("push button", f"Row {i}") for i in range(3)]
    listing = Node("panel", "", children=rows)
    vbar, hbar = FakeBar("vertical", increment=10), FakeBar("horizontal")
    pane = Node("scroll pane", "", children=[listing, vbar, hbar])
    frames["demo"].kids.append(pane)
    with_parents(frames["apps"][0])
    state = driver.get_window_state(1)
    return {"state": state, "vbar": vbar, "hbar": hbar, "pane": pane}


def find(state: Any, role: str, name: str = "") -> Any:
    return next(e for e in state.elements if e.role == role and (not name or e.name == name))


def test_scroll_moves_the_nearest_scroll_bar(driver: WaylandDriver, scrolled: dict[str, Any]) -> None:
    row = find(scrolled["state"], "push button", "Row 1")
    assert driver.scroll("down", 3, row)  # found by walking up from the row
    assert scrolled["vbar"].value == 30  # 3 steps of the bar's increment
    assert driver.scroll("up", 1, find(scrolled["state"], "scroll pane"))
    assert scrolled["vbar"].value == 20
    assert driver.scroll("right", 2, row)
    assert scrolled["hbar"].value == 10  # no increment: 5% of the range per step
    assert driver.scroll("down", 3, scrolled["state"].elements[0])  # from the window


def test_scroll_stops_at_the_end(driver: WaylandDriver, scrolled: dict[str, Any]) -> None:
    row = find(scrolled["state"], "push button", "Row 0")
    assert driver.scroll("down", 100, row)
    assert scrolled["vbar"].value == 100
    with pytest.raises(NotSupportedError, match="all the way down"):
        driver.scroll("down", 1, row)


def test_scroll_refuses_when_the_app_ignores_it(
    driver: WaylandDriver, scrolled: dict[str, Any]
) -> None:
    scrolled["vbar"].obeys = False
    with pytest.raises(NotSupportedError, match="didn't move its scroll bar"):
        driver.scroll("down", 1, find(scrolled["state"], "scroll pane"))


def test_scroll_refuses_without_a_scroll_bar(driver: WaylandDriver, frames: dict[str, Any]) -> None:
    with_parents(frames["apps"][0])
    root = driver.get_window_state(1).elements[0]
    with pytest.raises(NotSupportedError, match="no vertical scroll bar"):
        driver.scroll("down", 3, root)


def test_scroll_never_reaches_another_window(driver: WaylandDriver, frames: dict[str, Any]) -> None:
    """A bar in the app's other window must not be moved."""
    other_frame = Node("frame", "Second", children=[FakeBar("vertical")])
    frames["apps"][0].kids.append(other_frame)
    with_parents(frames["apps"][0])
    root = driver.get_window_state(1).elements[0]
    with pytest.raises(NotSupportedError, match="no vertical scroll bar"):
        driver.scroll("down", 1, root)


# --------------------------------------------------------------------------- #
# Phase 3: uinput keyboard
# --------------------------------------------------------------------------- #


class FakeUInputDevice:
    """Records ioctls and written events in place of /dev/uinput."""

    def __init__(self) -> None:
        self.ioctls: list[tuple[int, Any]] = []
        self.data = b""

    def ioctl(self, fd: int, request: int, arg: Any = 0) -> int:
        self.ioctls.append((request, arg))
        return 0

    def write(self, fd: int, data: bytes) -> int:
        self.data += data
        return len(data)


@pytest.fixture
def device(monkeypatch: pytest.MonkeyPatch) -> FakeUInputDevice:
    monkeypatch.setattr(uinput.time, "sleep", lambda _s: None)
    return FakeUInputDevice()


def make_keyboard(device: FakeUInputDevice, layout: str = "us") -> uinput.UInputKeyboard:
    return uinput.UInputKeyboard(
        layout, opener=lambda _p, _f: 99, ioctl=device.ioctl, writer=device.write
    )


def key_events(device: FakeUInputDevice) -> list[tuple[int, int]]:
    return [(code, value) for kind, code, value in uinput.decode(device.data) if kind == uinput.EV_KEY]


def test_uinput_device_setup(device: FakeUInputDevice) -> None:
    make_keyboard(device)
    requests = [r for r, _ in device.ioctls]
    assert requests[0] == uinput.UI_SET_EVBIT
    assert uinput.UI_DEV_SETUP in requests
    assert requests[-1] == uinput.UI_DEV_CREATE
    assert (uinput.UI_SET_KEYBIT, 30) in device.ioctls  # KEY_A
    assert uinput.UI_DEV_SETUP == 0x405C5503  # _IOW('U', 3, struct uinput_setup)


def test_uinput_types_with_shift_and_syncs(device: FakeUInputDevice) -> None:
    kb = make_keyboard(device)
    for sym in keysyms.text_keysyms("aA!"):
        kb.key(sym, pressed=True)
        kb.key(sym, pressed=False)
    assert key_events(device) == [
        (30, 1), (30, 0),
        (42, 1), (30, 1), (30, 0), (42, 0),
        (42, 1), (2, 1), (2, 0), (42, 0),
    ]
    kinds = [kind for kind, _, _ in uinput.decode(device.data)]
    assert kinds[1::2] == [uinput.EV_SYN] * (len(kinds) // 2)  # a report after every key


@pytest.mark.parametrize(("keys", "codes"), [
    ("Return", [28]), ("ctrl+c", [29, 46]), ("alt+F4", [56, 62]), ("F12", [88]), ("F13", [183]),
])
def test_uinput_named_keys(device: FakeUInputDevice, keys: str, codes: list[int]) -> None:
    kb = make_keyboard(device)
    for sym in keysyms.parse_combo(keys):
        kb.key(sym, pressed=True)
    assert [code for code, _ in key_events(device)] == codes


def test_uinput_refuses_unknown_layouts_and_missing_device(device: FakeUInputDevice) -> None:
    with pytest.raises(NotSupportedError, match="only us is supported"):
        make_keyboard(device, "fr")

    def denied(_p: str, _f: int) -> int:
        raise PermissionError

    with pytest.raises(NotSupportedError, match="udev rule"):
        uinput.UInputKeyboard("us", opener=denied, ioctl=device.ioctl, writer=device.write)


def test_driver_uses_uinput_with_the_same_focus_gate(
    driver: WaylandDriver, device: FakeUInputDevice, frames: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver.portal = None
    driver.uinput_layout = "us"
    driver._uinput_factory = lambda layout: make_keyboard(device, layout)
    assert driver.press_key("ctrl+a")
    assert key_events(device) == [(29, 1), (30, 1), (30, 0), (29, 0)]

    with pytest.raises(NotSupportedError, match="can't type 'é'"):
        driver.type_text("café", window_element(driver, 1))
    assert len(key_events(device)) == 4  # nothing typed, not even "caf"

    frames["demo"].kids.append(Node("password text", "Password"))
    with pytest.raises(NotSupportedError, match="password field"):
        driver.press_key("Return")
    assert len(key_events(device)) == 4


def test_uinput_is_opt_in() -> None:
    assert uinput.layout_name({}) is None
    assert uinput.layout_name({uinput.ENABLE_ENV: "US"}) == "us"
