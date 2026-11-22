"""The portal client against a fake xdg-desktop-portal on a private D-Bus.

python-dbusmock has no portal template, so this file serves a small fake
``org.freedesktop.portal.Desktop`` (Screenshot, RemoteDesktop, Request and
Session objects) from the test process itself. The client iterates the same
GLib main context while it waits, so both sides run in one thread.

Needs PyGObject and dbus-daemon; skipped otherwise. Real GNOME/KDE portals
are covered by the manual checklist in tests/manual/portal.md.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

gi = pytest.importorskip("gi")
try:
    from gi.repository import Gio, GLib
except ImportError:  # pragma: no cover
    pytest.skip("Gio is not available", allow_module_level=True)

from linux_computer_use.drivers import portal  # noqa: E402
from PIL import Image as PILImage  # noqa: E402

if shutil.which("dbus-daemon") is None:  # pragma: no cover
    pytest.skip("dbus-daemon is not installed", allow_module_level=True)

XML = """
<node>
  <interface name="org.freedesktop.portal.Screenshot">
    <method name="Screenshot">
      <arg type="s" direction="in"/><arg type="a{sv}" direction="in"/>
      <arg type="o" direction="out"/>
    </method>
  </interface>
  <interface name="org.freedesktop.portal.RemoteDesktop">
    <method name="CreateSession">
      <arg type="a{sv}" direction="in"/><arg type="o" direction="out"/>
    </method>
    <method name="SelectDevices">
      <arg type="o" direction="in"/><arg type="a{sv}" direction="in"/>
      <arg type="o" direction="out"/>
    </method>
    <method name="Start">
      <arg type="o" direction="in"/><arg type="s" direction="in"/>
      <arg type="a{sv}" direction="in"/><arg type="o" direction="out"/>
    </method>
    <method name="NotifyKeyboardKeysym">
      <arg type="o" direction="in"/><arg type="a{sv}" direction="in"/>
      <arg type="i" direction="in"/><arg type="u" direction="in"/>
    </method>
    <property name="AvailableDeviceTypes" type="u" access="read"/>
    <property name="version" type="u" access="read"/>
  </interface>
</node>
"""

SESSION_XML = """
<node>
  <interface name="org.freedesktop.portal.Session">
    <method name="Close"/>
    <signal name="Closed"><arg type="a{sv}"/></signal>
  </interface>
</node>
"""


class FakePortal:
    """Answers like xdg-desktop-portal; behaviour is set through attributes."""

    def __init__(self, address: str, shot_dir: Path) -> None:
        self.conn = Gio.DBusConnection.new_for_address_sync(
            address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None,
            None,
        )
        self.shot_dir = shot_dir
        self.version = 2
        self.devices = portal.KEYBOARD | portal.POINTER
        self.decline: set[str] = set()  # methods answered with "cancelled"
        self.valid_tokens: set[str] = set()
        self.dialogs = 0  # Start calls that had no valid restore token
        self.keys: list[tuple[int, int]] = []
        self.sessions: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []
        self._issued = 0

        node = Gio.DBusNodeInfo.new_for_xml(XML)
        for iface in node.interfaces:
            self.conn.register_object(
                portal.OBJECT_PATH, iface, self._on_call, self._on_get, None
            )
        self._session_iface = Gio.DBusNodeInfo.new_for_xml(SESSION_XML).interfaces[0]
        Gio.bus_own_name_on_connection(
            self.conn, portal.BUS_NAME, Gio.BusNameOwnerFlags.NONE, None, None
        )
        ctx = GLib.MainContext.default()
        for _ in range(200):  # wait for the name to be owned
            ctx.iteration(may_block=False)
        self._wait_owned()

    def _wait_owned(self) -> None:
        bus = self.conn
        for _ in range(500):
            reply = bus.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                "NameHasOwner", GLib.Variant("(s)", (portal.BUS_NAME,)),
                None, Gio.DBusCallFlags.NONE, 1000, None,
            )
            if reply.unpack()[0]:
                return
            GLib.MainContext.default().iteration(may_block=False)
        raise RuntimeError("fake portal could not own its name")

    # -- D-Bus handlers ----------------------------------------------------- #

    def _on_get(self, _c: Any, _s: Any, _p: Any, _i: Any, name: str) -> Any:
        return GLib.Variant("u", self.version if name == "version" else self.devices)

    def _request_path(self, sender: str, token: str) -> str:
        return f"{portal.OBJECT_PATH}/request/{sender.lstrip(':').replace('.', '_')}/{token}"

    def _respond(self, path: str, code: int, results: dict[str, Any]) -> bool:
        self.conn.emit_signal(
            None, path, portal.REQUEST_IFACE, "Response",
            GLib.Variant("(ua{sv})", (code, results)),
        )
        return False

    def _on_call(
        self, _c: Any, sender: str, _p: str, _iface: str, method: str, params: Any, inv: Any
    ) -> None:
        self.calls.append(method)
        args = params.unpack()
        if method == "NotifyKeyboardKeysym":
            session, _opts, keysym, state = args
            if session not in self.sessions or not self.sessions[session].get("started"):
                inv.return_dbus_error("org.freedesktop.DBus.Error.AccessDenied", "not started")
                return
            self.keys.append((keysym, state))
            inv.return_value(None)
            return
        options = args[-1]
        path = self._request_path(sender, options["handle_token"])
        inv.return_value(GLib.Variant("(o)", (path,)))
        code, results = 0, {}
        if method in self.decline:
            code = 1
        elif method == "Screenshot":
            shot = self.shot_dir / "Screenshot from fake.png"
            PILImage.new("RGB", (32, 24), "red").save(shot)
            results = {"uri": GLib.Variant("s", shot.as_uri())}
        elif method == "CreateSession":
            handle = (
                f"{portal.OBJECT_PATH}/session/{sender.lstrip(':').replace('.', '_')}/"
                f"{options['session_handle_token']}"
            )
            self.sessions[handle] = {"types": 0}
            self.conn.register_object(handle, self._session_iface, self._on_session, None, None)
            results = {"session_handle": GLib.Variant("s", handle)}
        elif method == "SelectDevices":
            session = self.sessions[args[0]]
            session["types"] = options.get("types", 0)
            session["restore"] = options.get("restore_token")
            session["persist"] = options.get("persist_mode", 0)
        elif method == "Start":
            session = self.sessions[args[0]]
            if session.get("restore") not in self.valid_tokens:
                self.dialogs += 1
            self.valid_tokens.discard(session.get("restore"))
            session["started"] = True
            results = {"devices": GLib.Variant("u", session["types"] & self.devices)}
            if session["persist"]:
                self._issued += 1
                token = f"token-{self._issued}"
                self.valid_tokens.add(token)
                results["restore_token"] = GLib.Variant("s", token)
        GLib.idle_add(self._respond, path, code, results)

    def _on_session(self, _c: Any, _s: Any, path: str, _i: Any, method: str, _p: Any, inv: Any) -> None:
        self.sessions.pop(path, None)
        inv.return_value(None)

    def close_session(self, handle: str) -> None:
        """The user ends the session from the desktop."""
        self.sessions.pop(handle, None)
        self.conn.emit_signal(
            None, handle, portal.SESSION_IFACE, "Closed", GLib.Variant("(a{sv})", ({},))
        )


@pytest.fixture
def bus() -> Any:
    # TestDBus changes the process environment behind Python's back: it
    # unsets DISPLAY and points DBUS_SESSION_BUS_ADDRESS at the private bus
    # (then unsets it). Re-assign every variable afterwards so the C
    # environment, which subprocesses inherit, matches os.environ again for
    # the X11 and AT-SPI tests that follow.
    saved = dict(os.environ)
    test_bus = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
    test_bus.up()
    try:
        yield test_bus.get_bus_address()
    finally:
        test_bus.down()
        for key, value in saved.items():
            os.environ[key] = value


@pytest.fixture
def fake(bus: str, tmp_path: Path) -> FakePortal:
    pictures = tmp_path / "Pictures"
    pictures.mkdir()
    return FakePortal(bus, pictures)


@pytest.fixture
def client(bus: str, tmp_path: Path) -> portal.Portal:
    temp = tmp_path / "session"
    temp.mkdir()
    return portal.Portal(
        tokens=portal.TokenStore(tmp_path / "state" / "token"),
        bus_address=bus,
        temp_dir=lambda: temp,
    )


def test_screenshot_is_moved_out_of_pictures(fake: FakePortal, client: portal.Portal, tmp_path: Path) -> None:
    path = Path(client.screenshot())
    assert path.parent == tmp_path / "session"
    assert path.stat().st_mode & 0o777 == 0o600
    with PILImage.open(path) as img:
        assert img.size == (32, 24)
    assert list(fake.shot_dir.iterdir()) == []  # nothing left in ~/Pictures


def test_screenshot_declined(fake: FakePortal, client: portal.Portal) -> None:
    fake.decline.add("Screenshot")
    with pytest.raises(portal.PortalError, match="screenshot request was declined"):
        client.screenshot()


def test_keyboard_session_sends_keysyms(fake: FakePortal, client: portal.Portal) -> None:
    session = client.remote_desktop()
    session.key(0xFF0D, pressed=True)
    session.key(0xFF0D, pressed=False)
    assert fake.keys == [(0xFF0D, 1), (0xFF0D, 0)]
    assert client.remote_desktop() is session  # reused, no second dialog
    assert fake.dialogs == 1
    assert fake.calls.count("CreateSession") == 1


def test_restore_token_skips_the_dialog_next_time(
    fake: FakePortal, client: portal.Portal, bus: str, tmp_path: Path
) -> None:
    client.remote_desktop()
    assert client.tokens.load() == "token-1"
    client.close()

    # A new server process, same stored token.
    again = portal.Portal(tokens=client.tokens, bus_address=bus)
    again.remote_desktop().key(0x61, pressed=True)
    assert fake.dialogs == 1
    assert again.tokens.load() == "token-2"  # each start replaces the token


def test_declined_keyboard_clears_a_rejected_token(fake: FakePortal, client: portal.Portal) -> None:
    client.tokens.save("stale")
    fake.decline.add("Start")
    with pytest.raises(portal.PortalError, match=r"wasn't granted.*declined"):
        client.remote_desktop()
    assert client.tokens.load() is None
    assert fake.sessions == {}  # the half-made session was closed


def test_session_closed_by_the_user(fake: FakePortal, client: portal.Portal) -> None:
    session = client.remote_desktop()
    fake.close_session(session.handle)
    for _ in range(200):  # the signal goes through dbus-daemon
        client.pump()
        if session.closed:
            break
        time.sleep(0.005)
    with pytest.raises(portal.PortalError, match="session was ended"):
        session.key(0x61, pressed=True)
    assert client.remote_desktop() is not session  # asks again


def test_no_keyboard_offered(fake: FakePortal, client: portal.Portal) -> None:
    fake.devices = portal.POINTER
    with pytest.raises(portal.PortalError, match="offers no keyboard"):
        client.remote_desktop()


def test_no_portal_running(bus: str, tmp_path: Path) -> None:
    lonely = portal.Portal(tokens=portal.TokenStore(tmp_path / "t"), bus_address=bus)
    with pytest.raises(portal.PortalError, match="No desktop portal is running"):
        lonely.screenshot()
    with pytest.raises(portal.PortalError, match="No desktop portal is running"):
        lonely.remote_desktop()


def test_gio_loads_in_a_fresh_process() -> None:
    """gi.repository loads typelibs lazily; Portal must import Gio itself
    (this file's own import would otherwise hide a failure)."""
    import subprocess
    import sys

    code = (
        "from linux_computer_use.drivers import portal; "
        "p = portal.Portal(); print(p.gio is not None and p.glib is not None)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "True", out.stderr
