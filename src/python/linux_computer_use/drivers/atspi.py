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

#: Containers with more children than this fetch only their showing children
#: in one Collection query instead of one call per child (big lists, grids).
BULK_CHILDREN = 32

#: Pixels by which an accessible window's position may differ from X11's and
#: still count as the same place (window decorations, CSD shadows).
MATCH_TOLERANCE = 64

#: Coordinates at or below this mean "no position" (toolkits report INT_MIN).
_NO_POSITION = -(1 << 30)

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
    #: Elements skipped because they lie entirely outside the window.
    offscreen: int = 0

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
        if self.offscreen:
            lines.append(
                f"... ({self.offscreen} elements outside the visible area not shown; "
                "scroll to bring them into view)"
            )
        if self.truncated:
            lines.append(f"... (tree truncated at {len(self.elements)} elements)")
        return "\n".join(lines)


class TreeCache:
    """Live accessibles from each window's most recent tree read.

    Keyed by (window_id, index), so actions can act on exactly the element
    the client saw, and re-read just that element instead of the tree.
    """

    def __init__(self) -> None:
        self._nodes: dict[tuple[int, int], Any] = {}
        self._parents: dict[tuple[int, int], int] = {}
        self._roots: dict[int, Any] = {}

    def forget(self, window_id: int) -> None:
        for key in [k for k in self._nodes if k[0] == window_id]:
            del self._nodes[key]
            self._parents.pop(key, None)
        self._roots.pop(window_id, None)

    def remember(self, window_id: int, root: Any, tree: AccessibleTree) -> None:
        self.forget(window_id)
        self._roots[window_id] = root
        for element, node in zip(tree.elements, tree.accessibles, strict=True):
            self._nodes[(window_id, element.index)] = node
            self._parents[(window_id, element.index)] = element.parent_index

    def node(self, window_id: int, index: int) -> Any | None:
        return self._nodes.get((window_id, index))

    def parent(self, window_id: int, index: int) -> int:
        return self._parents.get((window_id, index), -1)

    def root(self, window_id: int) -> Any | None:
        return self._roots.get(window_id)

    def items(self, window_id: int) -> list[tuple[int, Any]]:
        """(index, accessible) pairs for one window, in tree order."""
        return sorted(
            ((index, node) for (wid, index), node in self._nodes.items() if wid == window_id),
            key=lambda item: item[0],
        )


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
    # Finding windows
    # ------------------------------------------------------------------ #

    def list_frames(self) -> list[tuple[Any, Any]]:
        """(application, window) accessibles for every showing top-level window.

        Works on any display server; it is the only window list on Wayland.
        """
        if not self.connect():
            return []
        frames = []
        for app in _children(self._atspi.get_desktop(0)):  # type: ignore[union-attr]
            for window in _children(app):
                if _safe(window.get_role_name, "") not in WINDOW_ROLES:
                    continue
                if "showing" not in _state_nicks(window):
                    continue
                frames.append((app, window))
        return frames

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

    def extents(
        self, accessible: Any, offset: tuple[int, int] | None = None
    ) -> tuple[int, int, int, int] | None:
        """Screen rectangle of an accessible.

        With ``offset`` None, trusts the toolkit's screen coordinates. Otherwise
        reads window-relative coordinates and adds ``offset`` (see
        ``window_offset``), for toolkits whose screen coordinates are wrong.
        """
        rect = self._raw_extents(accessible, window=offset is not None)
        if rect is None or offset is None:
            return rect
        x, y, w, h = rect
        return (x + offset[0], y + offset[1], w, h)

    def _raw_extents(self, accessible: Any, *, window: bool) -> tuple[int, int, int, int] | None:
        try:
            component = accessible.get_component_iface()
            if component is None:
                return None
            coord = self._atspi.CoordType  # type: ignore[union-attr]
            rect = component.get_extents(coord.WINDOW if window else coord.SCREEN)
        except Exception:
            return None
        if rect.x <= _NO_POSITION or rect.y <= _NO_POSITION:
            return None  # toolkit has no position for it (e.g. a scrolled GTK viewport)
        return (rect.x, rect.y, rect.width, rect.height)

    def window_offset(
        self, root: Any, window_rect: tuple[int, int, int, int] | None
    ) -> tuple[int, int] | None:
        """How to turn this window's element positions into screen positions.

        Returns None when the toolkit's screen coordinates can be trusted, or an
        (x, y) offset to add to window-relative coordinates when they can't.
        GTK 4 reports every element at screen position 0,0 (on X11 as well as
        Wayland) while its window-relative positions are right; other toolkits
        are caught by their window's screen position disagreeing with X11's.
        """
        if window_rect is None:
            return None
        screen = self._raw_extents(root, window=False)
        trusted = not _is_gtk4_or_later(root) and screen is not None and all(
            abs(a - b) <= MATCH_TOLERANCE for a, b in zip(screen[:2], window_rect[:2], strict=True)
        )
        if trusted:
            return None
        relative = self._raw_extents(root, window=True)
        if relative is None:
            return None
        return (window_rect[0] - relative[0], window_rect[1] - relative[1])

    def read_tree(
        self,
        root: Any,
        window_id: int,
        screen: tuple[int, int, int, int] | None = None,
        offset: tuple[int, int] | None = None,
    ) -> AccessibleTree:
        """Flatten the visible part of an accessible tree, depth first.

        Skips hidden subtrees and subtrees lying entirely outside the window
        (e.g. rows of a long list below the fold), which nothing can click
        and which dominate the cost of reading large windows.
        """
        tree = AccessibleTree(elements=[], accessibles=[], depths=[])
        clip = self.extents(root, offset)
        if clip is not None and (clip[2] <= 0 or clip[3] <= 0):
            clip = None
        if screen is not None:
            # A window taller than the screen (no scroller) is only visible on screen.
            clip = _intersect(clip, screen) if clip is not None else screen
        self._walk(root, window_id, -1, 0, tree, clip, offset)
        return tree

    def _walk(
        self,
        node: Any,
        window_id: int,
        parent: int,
        depth: int,
        tree: AccessibleTree,
        clip: tuple[int, int, int, int] | None,
        offset: tuple[int, int] | None = None,
    ) -> None:
        if len(tree.elements) >= MAX_ELEMENTS:
            tree.truncated = True
            return
        states = _state_nicks(node)
        if parent >= 0 and "showing" not in states and not self._has_showing_descendant(node):
            return  # hidden subtree (collapsed menu, inactive tab, ...)
        rect = self.extents(node, offset) or (0, 0, 0, 0)
        if parent >= 0 and clip is not None and not _overlaps(rect, clip):
            tree.offscreen += 1
            return

        index = len(tree.elements)
        element = self._element(node, window_id, index, parent, states, rect)
        if element.role in PASSWORD_ROLES:
            tree.sensitive = True
            tree.sensitive_reasons.append(f"password field [{index}]")

        tree.elements.append(element)
        tree.accessibles.append(node)
        tree.depths.append(depth)
        if parent >= 0:
            tree.elements[parent].children.append(index)

        if depth >= MAX_DEPTH:
            return
        for child in self._showing_children(node):
            self._walk(child, window_id, index, depth + 1, tree, clip, offset)

    def _showing_rule(self) -> Any:
        atspi = self._atspi
        return atspi.MatchRule.new(  # type: ignore[union-attr]
            atspi.StateSet.new([atspi.StateType.SHOWING]),  # type: ignore[union-attr]
            atspi.CollectionMatchType.ALL,  # type: ignore[union-attr]
            {},
            atspi.CollectionMatchType.ALL,  # type: ignore[union-attr]
            [],
            atspi.CollectionMatchType.ALL,  # type: ignore[union-attr]
            [],
            atspi.CollectionMatchType.ALL,  # type: ignore[union-attr]
            False,
        )

    def _has_showing_descendant(self, node: Any) -> bool:
        """Whether a container that isn't "showing" still holds showing widgets.

        GTK 3 drops the showing state from a scrolled viewport while the rows
        inside it are on screen; trusting the container would hide them all.
        A hidden tab page has no showing descendants, so it is still skipped.
        One Collection query; without Collection, trust the container.
        """
        if self._atspi is None:
            return False
        try:
            collection = node.get_collection_iface()
            if collection is None:
                return False
            order = self._atspi.CollectionSortOrder.CANONICAL
            return bool(collection.get_matches(self._showing_rule(), order, 1, True))
        except Exception:
            return False

    def _showing_children(self, node: Any) -> list[Any]:
        """Children worth walking. For big containers, ask the app for only the
        showing ones in a single Collection query (a scrolled list of 1000 rows
        typically has a few dozen showing); otherwise fetch them one by one."""
        count = _safe(node.get_child_count, 0)
        if count > BULK_CHILDREN and self._atspi is not None:
            try:
                collection = node.get_collection_iface()
                if collection is not None:
                    order = self._atspi.CollectionSortOrder.CANONICAL
                    return list(collection.get_matches(self._showing_rule(), order, 0, False))
            except Exception:
                pass  # fall back to one call per child
        return _children(node)

    def _element(
        self,
        node: Any,
        window_id: int,
        index: int,
        parent: int,
        states: set[str],
        rect: tuple[int, int, int, int],
    ) -> Element:
        role = _safe(node.get_role_name, "unknown")
        x, y, w, h = rect
        return Element(
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

    def refresh(
        self,
        node: Any,
        window_id: int,
        index: int,
        parent: int,
        offset: tuple[int, int] | None = None,
    ) -> Element | None:
        """Re-read one element from its live accessible, without walking the tree.

        Returns None if the widget is gone or no longer showing, so callers
        never act on something the user can't see.
        """
        states = _state_nicks(node)
        if not states or "defunct" in states:
            return None
        if index != 0 and "showing" not in states:
            return None
        return self._element(
            node, window_id, index, parent, states, self.extents(node, offset) or (0, 0, 0, 0)
        )

    def find_sensitive(self, root: Any) -> list[str] | None:
        """Look for a showing password field anywhere under root in one query.

        Uses the AT-SPI Collection interface, which the app answers itself.
        Returns None when the app doesn't support Collection, so the caller
        can fall back to walking the tree.
        """
        if not self.connect():
            return None
        atspi = self._atspi
        try:
            collection = root.get_collection_iface()
            if collection is None:
                return None
            rule = atspi.MatchRule.new(  # type: ignore[union-attr]
                atspi.StateSet.new([atspi.StateType.SHOWING]),  # type: ignore[union-attr]
                atspi.CollectionMatchType.ALL,  # type: ignore[union-attr]
                {},
                atspi.CollectionMatchType.ALL,  # type: ignore[union-attr]
                [atspi.Role.PASSWORD_TEXT],  # type: ignore[union-attr]
                atspi.CollectionMatchType.ANY,  # type: ignore[union-attr]
                [],
                atspi.CollectionMatchType.ALL,  # type: ignore[union-attr]
                False,
            )
            matches = collection.get_matches(
                rule, atspi.CollectionSortOrder.CANONICAL, 1, True  # type: ignore[union-attr]
            )
        except Exception:
            return None
        return ["password field"] if matches else []

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

    def insert_text(self, accessible: Any, text: str) -> bool:
        """Insert text at the caret of an editable field via EditableText.

        The app edits its own field; no keyboard input is synthesized, so it
        works on Wayland. Returns False for non-editable elements.
        """
        if not self.connect() or "editable" not in _state_nicks(accessible):
            return False
        atspi = self._atspi
        try:
            if accessible.get_editable_text_iface() is None:
                return False
            count = atspi.Text.get_character_count(accessible)  # type: ignore[union-attr]
            caret = atspi.Text.get_caret_offset(accessible)  # type: ignore[union-attr]
            position = caret if 0 <= caret <= count else count
            return bool(
                atspi.EditableText.insert_text(  # type: ignore[union-attr]
                    accessible, position, text, len(text)
                )
            )
        except Exception:
            return False

    def scroll_by_value(self, accessible: Any, direction: str, amount: int) -> ScrollResult:
        """Scroll the nearest scroll bar around accessible by setting its value.

        The app moves its own scroll bar, as if the user dragged it, so no
        pointer input is needed (this is how scrolling works on Wayland). The
        bar is searched for inside accessible first, then around each of its
        ancestors. One step is the bar's minimum increment, or 5% of its range
        when the toolkit reports none.
        """
        vertical = direction in ("up", "down")
        sign = 1 if direction in ("down", "right") else -1
        bar = find_scroll_bar(accessible, vertical=vertical)
        if bar is None:
            return ScrollResult(found=False)
        try:
            value = bar.get_value_iface()
            if value is None:
                return ScrollResult(found=False)
            current = float(value.get_current_value())
            low, high = float(value.get_minimum_value()), float(value.get_maximum_value())
            step = float(value.get_minimum_increment() or 0)
        except Exception:
            return ScrollResult(found=False)
        if high <= low:
            return ScrollResult(found=True, moved=False, at_end=True)
        if step <= 0 or step > (high - low) / 4:
            step = (high - low) / 20
        target = min(high, max(low, current + sign * step * max(1, amount)))
        if target == current:
            return ScrollResult(found=True, moved=False, at_end=True)
        try:
            value.set_current_value(target)
            after = float(value.get_current_value())
        except Exception:
            return ScrollResult(found=True, moved=False)
        return ScrollResult(found=True, moved=after != current)

    def finish(self, tree: AccessibleTree, root: Any) -> AccessibleTree:
        """Catch password fields the walk skipped (off-screen) with one query."""
        if not tree.sensitive and self.find_sensitive(root):
            tree.sensitive = True
            tree.sensitive_reasons.append("password field (outside the visible area)")
        return tree

    def grab_focus(self, accessible: Any) -> bool:
        try:
            component = accessible.get_component_iface()
            return bool(component and component.grab_focus())
        except Exception:
            return False


# ---------------------------------------------------------------------- #
# Helpers (pure functions are unit-tested with fake accessibles)
# ---------------------------------------------------------------------- #


@dataclass
class ScrollResult:
    """What scroll_by_value found and did."""

    found: bool
    moved: bool = False
    at_end: bool = False


#: Bounds for the scroll bar search, so huge trees can't stall a scroll.
_SCROLL_SEARCH_NODES = 400
_SCROLL_SEARCH_DEPTH = 6
_SCROLL_SEARCH_ANCESTORS = 12


def find_scroll_bar(start: Any, *, vertical: bool) -> Any | None:
    """The nearest showing scroll bar with the given orientation: inside start
    first, then around each ancestor (an element inside a scrolled list)."""
    node, seen = start, 0
    for _ in range(_SCROLL_SEARCH_ANCESTORS + 1):
        if node is None:
            return None
        hit, seen = _search_scroll_bar(node, vertical, seen)
        if hit is not None or seen >= _SCROLL_SEARCH_NODES:
            return hit
        if _safe(node.get_role_name, "") in WINDOW_ROLES:
            return None  # never reach into the app's other windows
        node = _safe(node.get_parent, None)
    return None


def _search_scroll_bar(root: Any, vertical: bool, seen: int) -> tuple[Any | None, int]:
    level = [root]
    for _ in range(_SCROLL_SEARCH_DEPTH):
        nxt = []
        for node in level:
            seen += 1
            if seen > _SCROLL_SEARCH_NODES:
                return None, seen
            if _safe(node.get_role_name, "") == "scroll bar" and _is_vertical(node) == vertical:
                states = _state_nicks(node)
                if "showing" in states or not states:
                    return node, seen
            nxt.extend(_children(node))
        if not nxt:
            break
        level = nxt
    return None, seen


def _is_vertical(bar: Any) -> bool:
    states = _state_nicks(bar)
    if "vertical" in states:
        return True
    if "horizontal" in states:
        return False
    try:  # no orientation state: a tall bar is vertical
        rect = bar.get_component_iface().get_extents(1)  # CoordType.WINDOW
        return bool(rect.height > rect.width)
    except Exception:
        return True


def match_window(
    candidates: list[Any],
    title: str,
    geometry: tuple[int, int, int, int] | None,
    extents: Any,
    tolerance: int | None = None,
) -> Any | None:
    """Pick the accessible window that best matches an X11 window.

    Prefers the same title and position, then the same title, then the same
    position, then the only window the app has.
    """
    tolerance = MATCH_TOLERANCE if tolerance is None else tolerance

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


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """True if rect a intersects rect b. Zero-size rects count as overlapping:
    many containers report no size while their children do."""
    ax, ay, aw, ah = a
    if aw <= 0 or ah <= 0:
        return True
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _intersect(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return (x1, y1, max(0, x2 - x1), max(0, y2 - y1))


def _is_gtk4_or_later(node: Any) -> bool:
    """GTK 4+ reports every element at screen 0,0 over AT-SPI."""
    try:
        app = node.get_application()
        if str(app.get_toolkit_name()).lower() != "gtk":
            return False
        return int(str(app.get_toolkit_version()).split(".")[0]) >= 4
    except Exception:
        return False


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
