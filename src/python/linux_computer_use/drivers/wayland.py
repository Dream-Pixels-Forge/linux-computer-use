"""Wayland driver: desktop control through AT-SPI only.

Wayland does not let one client list, move or send input to another
client's windows. What still works on every compositor is the accessibility
bus, AT-SPI: apps publish their widget tree there and perform actions on
request. This driver uses only that:

- windows are the apps' top-level accessible frames;
- element positions are relative to the window (``coordinates: "window"``),
  because Wayland clients don't know where their window is on screen;
- clicks invoke the element's accessible action, and text is inserted with
  the EditableText interface, so the app acts itself and no input is
  synthesized.

With ``LCU_WAYLAND_PORTAL=1`` the desktop portal adds, after the user
approves it once:

- ``screenshot_desktop`` through the Screenshot portal;
- key presses and typing into the focused window through the RemoteDesktop
  portal. Wayland doesn't let this server pick the focused window, so every
  key is sent only after AT-SPI confirms that exactly one window is active,
  that it is the intended one, and that it shows no password field. Keyboard
  input stays off on desktops where that focus reporting hasn't been checked
  (see ``KEYBOARD_VERIFIED_DESKTOPS``).

``scroll`` moves the nearest scroll bar's value over AT-SPI, so it needs no
pointer either. Clicking by position is still refused: it needs the window's
place on screen, which Wayland doesn't reveal. ``Atspi.generate_keyboard_event``
is not used: on Wayland it reports success and delivers nothing.

See docs/design/wayland.md and docs/design/wayland-phase2.md.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any

from linux_computer_use.drivers import keysyms, portal
from linux_computer_use.drivers.atspi import ATSPIDriver, TreeCache, _safe, _state_nicks
from linux_computer_use.drivers.base import (
    Driver,
    Element,
    NotSupportedError,
    Window,
    WindowState,
)

#: Window-relative coordinates: AT-SPI's WINDOW extents with no offset.
_WINDOW_RELATIVE = (0, 0)

_NEEDS_INPUT = (
    "needs synthesized keyboard or pointer input, which this server can't do on "
    "Wayland yet (planned via the RemoteDesktop portal; see docs/design/wayland.md)"
)

_NEEDS_POSITION = (
    "needs the window's position on screen, which Wayland doesn't tell other "
    "programs (see docs/design/wayland-phase2.md, slice 2d)"
)

#: Desktops (XDG_CURRENT_DESKTOP entries, lower case) where AT-SPI has been
#: shown to report the focused window accurately and promptly. Keyboard input
#: is only sent on these, because a key sent while another window has focus
#: lands in that window. GNOME: the focus check passed on 2026-11-22 (see
#: docs/design/wayland-phase2.md). KDE has not been checked yet.
KEYBOARD_VERIFIED_DESKTOPS: frozenset[str] = frozenset({"gnome"})

#: Operator override to try keyboard input on an unverified desktop.
KEYBOARD_UNVERIFIED_ENV = "LCU_WAYLAND_KEYBOARD_UNVERIFIED"

#: Characters typed between focus re-checks.
TYPE_CHUNK = 16


class WaylandDriver(Driver):
    """Driver for Wayland sessions, built on AT-SPI."""

    #: Element and window positions are window-relative, never screen pixels.
    positions_on_screen = False

    def __init__(self, portal_client: portal.Portal | None = None) -> None:
        self.atspi = ATSPIDriver()
        if portal_client is None and portal.enabled():
            portal_client = portal.Portal(temp_dir=_session_temp_dir)
        #: Desktop portal client, or None when portal use is not enabled.
        self.portal = portal_client
        self._tree = TreeCache()
        # Per-session window ids for accessible frames, keyed by (pid, object path).
        self._ids: dict[tuple[int, str], int] = {}
        self._frames: dict[int, tuple[Any, Any]] = {}
        self._next_id = 1

    def connect(self) -> bool:
        """True when the AT-SPI bus is reachable."""
        return self.atspi.connect()

    # ------------------------------------------------------------------ #
    # Windows
    # ------------------------------------------------------------------ #

    def _scan(self) -> list[int]:
        """Refresh the frame list; return window ids in desktop order."""
        frames: dict[int, tuple[Any, Any]] = {}
        order = []
        for app, frame in self.atspi.list_frames():
            pid = _safe(app.get_process_id, 0)
            key = (pid, str(_safe(lambda f=frame: f.path, "") or id(frame)))
            window_id = self._ids.get(key)
            if window_id is None:
                window_id = self._ids[key] = self._next_id
                self._next_id += 1
            frames[window_id] = (app, frame)
            order.append(window_id)
        for gone in set(self._frames) - set(frames):
            self._tree.forget(gone)
        self._frames = frames
        return order

    def _window(self, window_id: int, app: Any, frame: Any) -> Window:
        _, _, width, height = self.atspi.extents(frame, _WINDOW_RELATIVE) or (0, 0, 0, 0)
        name = _safe(app.get_name, "") or ""
        return Window(
            window_id=window_id,
            pid=_safe(app.get_process_id, 0),
            app_id=name,
            title=_safe(frame.get_name, "") or "",
            x=0,
            y=0,
            width=width,
            height=height,
            workspace=0,
            visible=True,
            app=name,
        )

    def list_windows(self) -> list[Window]:
        """Showing top-level windows of accessible apps. Positions are 0,0:
        on Wayland a window's place on screen is not known to clients."""
        return [self._window(wid, *self._frames[wid]) for wid in self._scan()]

    def get_window(self, window_id: int) -> Window | None:
        entry = self._frames.get(window_id)
        if entry is None or "showing" not in _state_nicks(entry[1]):
            self._scan()
            entry = self._frames.get(window_id)
        if entry is None:
            return None
        return self._window(window_id, *entry)

    def get_window_state(self, window_id: int) -> WindowState:
        """The window's accessible tree, with window-relative positions."""
        if self.get_window(window_id) is None:
            return WindowState(window_id, 0, "", "No elements found", [], coordinates="window")
        app, frame = self._frames[window_id]
        tree = self.atspi.read_tree(frame, window_id, None, _WINDOW_RELATIVE)
        if not tree.elements:
            self._tree.forget(window_id)
            return WindowState(window_id, 0, "", "No elements found", [], coordinates="window")
        self._tree.remember(window_id, frame, tree)
        self.atspi.finish(tree, frame)
        return WindowState(
            window_id=window_id,
            pid=_safe(app.get_process_id, 0),
            screenshot_path="",
            tree_markdown=tree.to_markdown(),
            elements=tree.elements,
            source="atspi",
            sensitive=tree.sensitive,
            sensitive_reasons=tree.sensitive_reasons,
            truncated=tree.truncated,
            offscreen=tree.offscreen,
            coordinates="window",
        )

    def resolve_element(self, window_id: int, index: int) -> Element | None:
        node = self._tree.node(window_id, index)
        if node is None:
            return None
        return self.atspi.refresh(
            node, window_id, index, self._tree.parent(window_id, index), _WINDOW_RELATIVE
        )

    def check_sensitive(self, window_id: int) -> list[str]:
        root = self._tree.root(window_id)
        if root is not None:
            reasons = self.atspi.find_sensitive(root)
            if reasons is not None:
                return reasons
        # No Collection support (GTK 4) or not read yet: walk the tree.
        return self.get_window_state(window_id).sensitive_reasons

    def _active_windows(self) -> list[int]:
        return [wid for wid in self._scan() if "active" in _state_nicks(self._frames[wid][1])]

    def get_focused_window(self) -> int | None:
        """The window whose frame is active, if exactly one reports it."""
        active = self._active_windows()
        return active[0] if len(active) == 1 else None

    def _require_focus(self, window_id: int | None) -> int:
        """The focused window, after checking it is safe to send keys to.

        Exactly one window must report itself active, it must be window_id
        when one is given, and it must not show a password field.
        """
        active = self._active_windows()
        if not active:
            raise NotSupportedError(
                "No window reports keyboard focus, so a key could land anywhere. Ask the "
                "user to click into the window to use, then retry. (Chrome and Electron "
                "apps only report focus when started with accessibility turned on, e.g. "
                "--force-renderer-accessibility.)"
            )
        if len(active) > 1:
            raise NotSupportedError(
                f"Windows {', '.join(map(str, active))} all report focus, so it's unclear "
                "where keys would go. Not sending any."
            )
        focused = active[0]
        if window_id is not None and focused != window_id:
            title = _safe(self._frames[focused][1].get_name, "") or ""
            raise NotSupportedError(
                f"Window {window_id} doesn't have keyboard focus; window {focused} ({title!r}) "
                "does. Wayland doesn't let this server switch windows: ask the user to bring "
                f"window {window_id} to the front, then retry."
            )
        reasons = self.check_sensitive(focused)
        if reasons:
            raise NotSupportedError(
                f"The focused window {focused} contains a {', '.join(reasons)}. "
                "linux-computer-use does not type into windows that ask for secrets."
            )
        return focused

    def _keyboard_allowed(self) -> portal.Portal:
        """The portal, if keyboard input is enabled and allowed on this desktop."""
        if self.portal is None:
            raise NotSupportedError(
                f"Sending keys {_NEEDS_INPUT}. Text can still be entered into a field: pass "
                f"type_text the index of an editable element. {portal.OPT_IN_HINT}"
            )
        desktops = {
            d.strip().lower() for d in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":") if d
        }
        if not desktops & KEYBOARD_VERIFIED_DESKTOPS and not portal.truthy(
            os.environ.get(KEYBOARD_UNVERIFIED_ENV)
        ):
            name = os.environ.get("XDG_CURRENT_DESKTOP") or "this desktop"
            raise NotSupportedError(
                f"Keyboard input is switched off on {name}: it hasn't yet been checked that "
                "this desktop reports the focused window accurately, and a key sent to the "
                f"wrong window could do harm. Set {KEYBOARD_UNVERIFIED_ENV}=1 to try it anyway."
            )
        return self.portal

    def _keyboard(self) -> portal.RemoteDesktopSession:
        """The portal keyboard session (may show the permission dialog)."""
        client = self._keyboard_allowed()
        client.pump()  # notice a session the user closed
        return client.remote_desktop()

    def _send(self, session: portal.RemoteDesktopSession, combo: list[int]) -> None:
        """Press the keys in order and release them in reverse, even on error."""
        pressed: list[int] = []
        try:
            for sym in combo:
                session.key(sym, pressed=True)
                pressed.append(sym)
        finally:
            for sym in reversed(pressed):
                with contextlib.suppress(NotSupportedError):
                    session.key(sym, pressed=False)

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def click(self, element: Element) -> bool:
        """Invoke the element's accessible click/press/toggle action."""
        node = self._tree.node(element.window_id, element.index)
        if node is not None and self.atspi.do_click_action(node):
            return True
        raise NotSupportedError(
            f"Element {element.index} ({element.role}) has no accessible click action, and "
            f"clicking it by position {_NEEDS_INPUT}."
        )

    def type_text(self, text: str, element: Element) -> bool:
        """Insert text into an editable field via EditableText, or, with element
        index 0, type it into the focused window through the portal keyboard."""
        if element.index == 0:
            return self._type_keys(text, element.window_id)
        node = self._tree.node(element.window_id, element.index)
        if node is not None and self.atspi.insert_text(node, text):
            return True
        raise NotSupportedError(
            f"Element {element.index} ({element.role}) is not an editable text field, "
            f"and typing into it {_NEEDS_INPUT}."
        )

    def _type_keys(self, text: str, window_id: int) -> bool:
        try:
            syms = keysyms.text_keysyms(text)
        except keysyms.KeyNameError as exc:
            raise NotSupportedError(str(exc)) from None
        self._keyboard_allowed()
        self._require_focus(window_id)  # before any permission dialog
        session = self._keyboard()
        for start in range(0, len(syms), TYPE_CHUNK):
            # Focus can move while typing; stop rather than type elsewhere.
            self._require_focus(window_id)
            for sym in syms[start : start + TYPE_CHUNK]:
                self._send(session, [sym])
        return True

    def focus_window(self, window_id: int) -> bool:
        """Wayland can't switch windows for us; succeed only if it already has focus."""
        if self.portal is None:
            raise NotSupportedError(
                f"Focusing a window (needed to press keys or type into whatever has focus) "
                f"{_NEEDS_INPUT}. Text can still be entered: pass type_text the index of an "
                f"editable element. {portal.OPT_IN_HINT}"
            )
        self._require_focus(window_id)
        return True

    def click_coordinate(self, x: int, y: int) -> bool:
        raise NotSupportedError(f"Clicking by position {_NEEDS_POSITION}. Click an element instead.")

    def press_key(self, keys: str, element: Element | None = None) -> bool:
        """Press a key combination in the focused window through the portal."""
        try:
            combo = keysyms.parse_combo(keys)
        except keysyms.KeyNameError as exc:
            raise NotSupportedError(str(exc)) from None
        target = element.window_id if element is not None else None
        self._keyboard_allowed()
        self._require_focus(target)  # before any permission dialog
        session = self._keyboard()
        self._require_focus(target)  # the dialog may have moved focus
        self._send(session, combo)
        return True

    def scroll(self, direction: str, amount: int, element: Element) -> bool:
        """Scroll by moving the nearest scroll bar's value over AT-SPI.

        Wayland gives no pointer to wheel with, but the app will move its own
        scroll bar on request. Refuses when there is no scroll bar to move.
        """
        node = self._tree.node(element.window_id, element.index)
        if node is None and element.index == 0 and element.window_id in self._frames:
            node = self._frames[element.window_id][1]
        if node is None:
            raise NotSupportedError(
                f"Element {element.index} is no longer available; call get_window_state again."
            )
        result = self.atspi.scroll_by_value(node, direction, amount)
        axis = "vertical" if direction in ("up", "down") else "horizontal"
        if not result.found:
            raise NotSupportedError(
                f"Element {element.index} ({element.role}) has no {axis} scroll bar around it "
                "that accessibility can move, and wheel scrolling on Wayland "
                f"{_NEEDS_POSITION}. Pass the index of the scrolled list or an item in it."
            )
        if result.at_end:
            raise NotSupportedError(f"Already scrolled all the way {direction}.")
        if not result.moved:
            raise NotSupportedError(
                f"The app didn't move its scroll bar when asked (Wayland scrolling uses "
                f"accessibility, and this {axis} scroll bar ignored it)."
            )
        return True

    def screenshot_window(self, window_id: int) -> str:
        raise NotSupportedError(
            f"A window screenshot {_NEEDS_POSITION}. "
            + ("Use screenshot_desktop instead." if self.portal else _NO_CAPTURE)
        )

    def screenshot_desktop(self, region: tuple[int, int, int, int] | None = None) -> str:
        """The whole screen through the Screenshot portal."""
        if self.portal is None:
            raise NotSupportedError(f"{_NO_CAPTURE} {portal.OPT_IN_HINT}")
        return self.portal.screenshot()

    def sensitive_windows(self) -> list[int]:
        """Showing windows that contain a password field."""
        return [wid for wid in self._scan() if self.check_sensitive(wid)]


def _session_temp_dir() -> Any:
    from linux_computer_use.session import get_active_session

    return get_active_session().temp_dir


_NO_CAPTURE = (
    "Screenshots on Wayland need the desktop's Screenshot portal, which is off by default "
    "(see docs/design/wayland-phase2.md). Use get_window_state to read the window."
)
