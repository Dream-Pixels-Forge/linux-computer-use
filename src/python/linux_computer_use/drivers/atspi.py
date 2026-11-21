"""AT-SPI accessibility tree reader.

AT-SPI is the Linux accessibility bus (used by screen readers). GTK, Qt,
Firefox, Chromium, LibreOffice and most other toolkits publish their widget
tree on it, which gives real buttons, text fields and menus instead of a bare
window rectangle.

This module does not drive input or take screenshots; the X11 driver does
that and uses this module for the element tree and for invoking accessible
actions (e.g. pressing a button without moving the mouse).

Requires PyGObject and the AT-SPI typelib (``pip install PyGObject`` plus the
``gir1.2-atspi-2.0`` package on Debian/Ubuntu). Everything degrades to "not
available" when they are missing.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any

from linux_computer_use.drivers.base import Element

logger = logging.getLogger(__name__)

#: Stop walking after this many elements so huge trees (spreadsheets, long
#: lists) can't stall the server.
MAX_ELEMENTS = 1000
MAX_DEPTH = 40

#: Roles that mean "a secret is typed here".
PASSWORD_ROLES = frozenset({"password text"})

#: Top-level roles an application uses for its windows.
WINDOW_ROLES = frozenset({"frame", "dialog", "window", "alert", "file chooser"})

#: Accessible action names that mean "activate this like a click".
CLICK_ACTIONS = ("click", "press", "toggle", "jump", "open")

#: AT-SPI states worth reporting, by their AT-SPI nick.
REPORTED_STATES = (
    "focused", "focusable", "checked", "selected", "expanded", "collapsed",
    "editable", "pressed", "active", "modal", "multi-line", "required",
)

#: Longest field value reported, in characters.
MAX_VALUE_CHARS = 500

#: Seconds to wait for one AT-SPI call before giving up on a frozen app.
CALL_TIMEOUT_MS = 2000


@dataclass
class AccessibleTree:
    """A flattened accessible tree for one window."""

    elements: list[Element]
    accessibles: list[Any]
    depths: list[int]
    truncated: bool = False
    sensitive: bool = False
    sensitive_reasons: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Render as an indented list an agent can read."""
        if not self.elements:
            return "No elements found"
        lines = []
        for element, depth in zip(self.elements, self.depths, strict=True):
            line = f"{'  ' * depth}- [{element.index}] {element.role}"
            if element.name:
                line += f' "{element.name}"'
            if element.actions:
                line += f" ({', '.join(element.actions)})"
            if element.value:
                line += f" = {element.value[:80]!r}"
            if element.state:
                line += f" {{{', '.join(element.state)}}}"
            lines.append(line)
        if self.truncated:
            lines.append(f"... (tree truncated at {len(self.elements)} elements)")
        return "\n".join(lines)


def _load_atspi() -> Any | None:
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
    except (ImportError, ValueError):
        return None
    return Atspi


class ATSPIDriver:
    """Reads accessible trees and invokes accessible actions over AT-SPI."""

    def __init__(self) -> None:
        self._atspi: Any | None = None
        self._tried = False

    @property
    def available(self) -> bool:
        """True when PyGObject and the AT-SPI typelib can be loaded."""
        return self.connect()

    def connect(self) -> bool:
        if not self._tried:
            self._tried = True
            self._atspi = _load_atspi()
            if self._atspi is None:
                logger.info("AT-SPI not available; element trees fall back to window outlines")
            else:
                self._atspi.set_timeout(CALL_TIMEOUT_MS, CALL_TIMEOUT_MS)
        return self._atspi is not None

    # ------------------------------------------------------------------ #
    # Finding a window's accessible
    # ------------------------------------------------------------------ #

    def find_window(
        self, pid: int, title: str, geometry: tuple[int, int, int, int] | None
    ) -> Any | None:
        """Find the accessible for an X11 window by owning PID, title and geometry."""
        if not pid or not self.connect():
            return None
        desktop = self._atspi.get_desktop(0)  # type: ignore[union-attr]
        candidates: list[Any] = []
        for app in _children(desktop):
            if _safe(app.get_process_id, 0) != pid:
                continue
            candidates.extend(
                w for w in _children(app) if _safe(w.get_role_name, "") in WINDOW_ROLES
            )
        return match_window(candidates, title, geometry, self.extents)

    # ------------------------------------------------------------------ #
    # Reading the tree
    # ------------------------------------------------------------------ #

    def extents(self, accessible: Any) -> tuple[int, int, int, int] | None:
        try:
            component = accessible.get_component_iface()
            if component is None:
                return None
            rect = component.get_extents(self._atspi.CoordType.SCREEN)  # type: ignore[union-attr]
        except Exception:
            return None
        return (rect.x, rect.y, rect.width, rect.height)

    def read_tree(self, root: Any, window_id: int) -> AccessibleTree:
        """Flatten the visible part of an accessible tree, depth first."""
        tree = AccessibleTree(elements=[], accessibles=[], depths=[])
        self._walk(root, window_id, -1, 0, tree)
        return tree

    def _walk(
        self, node: Any, window_id: int, parent: int, depth: int, tree: AccessibleTree
    ) -> None:
        if len(tree.elements) >= MAX_ELEMENTS:
            tree.truncated = True
            return
        states = _state_nicks(node)
        if parent >= 0 and "showing" not in states:
            return  # hidden subtree (collapsed menu, inactive tab, ...)

        index = len(tree.elements)
        role = _safe(node.get_role_name, "unknown")
        x, y, w, h = self.extents(node) or (0, 0, 0, 0)
        element = Element(
            index=index,
            role=role,
            name=_safe(node.get_name, "") or "",
            description=_safe(node.get_description, "") or "",
            state=_reported_states(states),
            x=x, y=y, width=w, height=h,
            parent_index=parent,
            automation_id=_safe(node.get_accessible_id, "") or "",
            window_id=window_id,
            actions=_action_names(node),
            value=(
                self._text_value(node)
                if "editable" in states and role not in PASSWORD_ROLES
                else None
            ),
        )
        if role in PASSWORD_ROLES:
            tree.sensitive = True
            tree.sensitive_reasons.append(f"password field [{index}]")

        tree.elements.append(element)
        tree.accessibles.append(node)
        tree.depths.append(depth)
        if parent >= 0:
            tree.elements[parent].children.append(index)

        if depth >= MAX_DEPTH:
            return
        for child in _children(node):
            self._walk(child, window_id, index, depth + 1, tree)

    def _text_value(self, node: Any) -> str | None:
        """Current text of an editable field, via the AT-SPI Text interface.

        Called as ``Atspi.Text.get_text(node, ...)`` because in PyGObject
        ``node.get_text`` resolves to an unrelated Accessible method.
        """
        try:
            if node.get_text_iface() is None:
                return None
            text_iface = self._atspi.Text  # type: ignore[union-attr]
            count = text_iface.get_character_count(node)
            return str(text_iface.get_text(node, 0, min(count, MAX_VALUE_CHARS)))
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Acting on accessibles
    # ------------------------------------------------------------------ #

    def do_click_action(self, accessible: Any) -> bool:
        """Invoke the element's click-like accessible action, if it has one."""
        names = _action_names(accessible)
        for wanted in CLICK_ACTIONS:
            if wanted in names:
                try:
                    return bool(accessible.get_action_iface().do_action(names.index(wanted)))
                except Exception:
                    return False
        return False

    def grab_focus(self, accessible: Any) -> bool:
        try:
            component = accessible.get_component_iface()
            return bool(component and component.grab_focus())
        except Exception:
            return False


# ---------------------------------------------------------------------- #
# Helpers (pure functions are unit-tested with fake accessibles)
# ---------------------------------------------------------------------- #


def match_window(
    candidates: list[Any],
    title: str,
    geometry: tuple[int, int, int, int] | None,
    extents: Any,
    tolerance: int = 64,
) -> Any | None:
    """Pick the accessible window that best matches an X11 window.

    Prefers the same title and position, then the same title, then the same
    position, then the only window the app has.
    """
    def near(acc: Any) -> bool:
        if geometry is None:
            return False
        ext = extents(acc)
        return ext is not None and all(
            abs(a - b) <= tolerance for a, b in zip(ext, geometry, strict=True)
        )

    titled = [c for c in candidates if title and _safe(c.get_name, "") == title]
    for group in ([c for c in titled if near(c)], titled, [c for c in candidates if near(c)]):
        if len(group) >= 1:
            return group[0]
    return candidates[0] if len(candidates) == 1 else None


def _children(node: Any) -> list[Any]:
    count = _safe(node.get_child_count, 0)
    out = []
    for i in range(count):
        child = _safe(lambda i=i: node.get_child_at_index(i), None)
        if child is not None:
            out.append(child)
    return out


def _state_nicks(node: Any) -> set[str]:
    try:
        return {s.value_nick for s in node.get_state_set().get_states()}
    except Exception:
        return set()


def _reported_states(nicks: set[str]) -> list[str]:
    states = [s for s in REPORTED_STATES if s in nicks]
    if "sensitive" not in nicks and "enabled" not in nicks:
        states.append("disabled")
    return states


def _action_names(node: Any) -> list[str]:
    try:
        action = node.get_action_iface()
        if action is None:
            return []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return [action.get_action_name(i) for i in range(action.get_n_actions())]
    except Exception:
        return []


def _safe(fn: Any, default: Any) -> Any:
    """Call an AT-SPI getter; apps can vanish or time out mid-walk."""
    try:
        return fn()
    except Exception:
        return default
