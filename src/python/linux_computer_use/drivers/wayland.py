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

Anything that needs real input (key presses, scrolling, clicking by
position, typing into whatever has focus) or screen capture raises
NotSupportedError with the reason. ``Atspi.generate_keyboard_event`` is not
used: on Wayland it reports success and delivers nothing.

See docs/design/wayland.md for the options considered and the plan for
portal-based input.
"""

from __future__ import annotations

from typing import Any

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


class WaylandDriver(Driver):
    """Driver for Wayland sessions, built on AT-SPI."""

    def __init__(self) -> None:
        self.atspi = ATSPIDriver()
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

    def get_focused_window(self) -> int | None:
        """The window whose frame is active, if the toolkit reports one."""
        for window_id in self._scan():
            if "active" in _state_nicks(self._frames[window_id][1]):
                return window_id
        return None

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
        """Insert text into an editable field at its caret, via EditableText."""
        if element.index == 0:
            raise NotSupportedError(
                f"Typing into whatever has focus {_NEEDS_INPUT}. Pass the index of an "
                "editable element instead."
            )
        node = self._tree.node(element.window_id, element.index)
        if node is not None and self.atspi.insert_text(node, text):
            return True
        raise NotSupportedError(
            f"Element {element.index} ({element.role}) is not an editable text field, "
            f"and typing into it {_NEEDS_INPUT}."
        )

    def focus_window(self, window_id: int) -> bool:
        raise NotSupportedError(
            f"Focusing a window (needed to press keys or type into whatever has focus) "
            f"{_NEEDS_INPUT}. Text can still be entered: pass type_text the index of an "
            "editable element."
        )

    def click_coordinate(self, x: int, y: int) -> bool:
        raise NotSupportedError(f"Clicking by position {_NEEDS_INPUT}. Click an element instead.")

    def press_key(self, keys: str, element: Element | None = None) -> bool:
        raise NotSupportedError(f"Pressing keys {_NEEDS_INPUT}.")

    def scroll(self, direction: str, amount: int, element: Element) -> bool:
        raise NotSupportedError(f"Scrolling {_NEEDS_INPUT}.")

    def screenshot_window(self, window_id: int) -> str:
        raise NotSupportedError(_NO_CAPTURE)

    def screenshot_desktop(self, region: tuple[int, int, int, int] | None = None) -> str:
        raise NotSupportedError(_NO_CAPTURE)


_NO_CAPTURE = (
    "Screenshots on Wayland need the Screenshot or ScreenCast portal, which this server "
    "doesn't use yet (see docs/design/wayland.md). Use get_window_state to read the window."
)
