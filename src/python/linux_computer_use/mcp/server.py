"""MCP server for linux_computer_use.

Built on the MCP Python SDK v2 high-level server (``MCPServer``, formerly
``FastMCP``). Tools are registered with decorators and their input schemas are
generated from the function signatures.

Run it with ``python -m linux_computer_use.mcp`` or ``linux-computer-use start``.
"""

from __future__ import annotations

import configparser
import json
import logging
import os
from pathlib import Path
from typing import Any, Literal, Protocol

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image as PILImage

from linux_computer_use import __version__
from linux_computer_use.drivers.base import Element, Window, WindowState
from linux_computer_use.session import get_active_session

logger = logging.getLogger(__name__)

SERVER_NAME = "linux-computer-use"


class DesktopDriver(Protocol):
    """The driver surface the MCP server relies on."""

    def connect(self) -> bool: ...
    def list_windows(self) -> list[Window]: ...
    def get_window_state(self, window_id: int) -> WindowState: ...
    def click(self, element: Element) -> bool: ...
    def click_coordinate(self, x: int, y: int) -> bool: ...
    def type_text(self, text: str, element: Element) -> bool: ...
    def press_key(self, keys: str, element: Element | None = None) -> bool: ...
    def scroll(self, direction: str, amount: int, element: Element) -> bool: ...
    def focus_window(self, window_id: int) -> bool: ...
    def get_focused_window(self) -> int | None: ...
    def screenshot_desktop(self, region: tuple[int, int, int, int] | None = None) -> str: ...


# --------------------------------------------------------------------------- #
# Driver management
# --------------------------------------------------------------------------- #

_driver: DesktopDriver | None = None


def get_driver() -> DesktopDriver:
    """Return the active driver, creating the X11 driver on first use."""
    global _driver
    if _driver is None:
        from linux_computer_use.drivers.x11 import X11Driver

        driver = X11Driver()
        if not driver.connect():
            raise ToolError(
                "Could not connect to an X11 display. Check that DISPLAY is set "
                "and that xdotool and scrot are installed."
            )
        _driver = driver
    return _driver


def set_driver(driver: DesktopDriver | None) -> None:
    """Replace the active driver (used by tests and alternative backends)."""
    global _driver
    _driver = driver


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _find_window(driver: DesktopDriver, window_id: int) -> Window:
    for window in driver.list_windows():
        if window.window_id == window_id:
            return window
    raise ToolError(f"Window {window_id} not found. Call list_windows for valid ids.")


# What each window looked like when the client last read it:
# window_id -> {index: (role, name)}. Element indexes are only meaningful
# relative to such a snapshot.
_snapshots: dict[int, dict[int, tuple[str, str]]] = {}


def _remember(state: WindowState) -> None:
    _snapshots[state.window_id] = {e.index: (e.role, e.name) for e in state.elements}


def _refuse_if_sensitive(state: WindowState) -> None:
    if state.sensitive:
        reasons = ", ".join(state.sensitive_reasons) or "sensitive input"
        raise ToolError(
            f"Window {state.window_id} contains a {reasons}. linux-computer-use does not "
            "interact with windows that ask for secrets; ask the user to complete this step."
        )


def _window_state(driver: DesktopDriver, window_id: int, *, acting: bool) -> WindowState:
    _find_window(driver, window_id)
    state = driver.get_window_state(window_id)
    if acting:
        _refuse_if_sensitive(state)
    return state


def _find_element(
    driver: DesktopDriver, window_id: int, index: int, *, acting: bool = True
) -> Element:
    """Resolve an element index against a fresh tree, refusing stale targets.

    Index 0 (the window itself) is always valid. Any other index must come
    from a get_window_state call, and the element at that index must still
    have the same role and name, so a UI change can't redirect an action
    to a different control.
    """
    state = _window_state(driver, window_id, acting=acting)
    element = next((e for e in state.elements if e.index == index), None)
    if index != 0:
        seen = _snapshots.get(window_id)
        if seen is None:
            raise ToolError(
                f"Call get_window_state({window_id}) first; element indexes come from it."
            )
        expected = seen.get(index)
        actual = (element.role, element.name) if element else None
        if expected is None:
            raise ToolError(f"Element {index} was not in the last get_window_state result.")
        if actual != expected:
            now = f'{actual[0]} "{actual[1]}"' if actual else "gone"
            raise ToolError(
                f'Element {index} changed since get_window_state (was {expected[0]} '
                f'"{expected[1]}", now {now}). Call get_window_state again.'
            )
    if element is None:
        raise ToolError(
            f"Element {index} not found in window {window_id}. "
            "Call get_window_state for a fresh element list."
        )
    return element


def _audit(tool: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    get_active_session().audit_action(tool, args, result)
    return result


def _capture(driver: DesktopDriver, region: tuple[int, int, int, int] | None, name: str) -> Path:
    """Capture the desktop, optionally cropped to (x, y, width, height)."""
    source = driver.screenshot_desktop()
    if not source:
        raise ToolError("Screenshot failed. Check that scrot is installed.")

    out = get_active_session().temp_dir / f"{name}.png"
    with PILImage.open(source) as shot:
        img: PILImage.Image = shot
        if region is not None:
            x, y, w, h = region
            if w <= 0 or h <= 0:
                raise ToolError(f"Invalid region size {w}x{h}.")
            left, top = max(0, x), max(0, y)
            right, bottom = min(img.width, x + w), min(img.height, y + h)
            if right <= left or bottom <= top:
                raise ToolError("Region lies outside the screen.")
            img = img.crop((left, top, right, bottom))
        img.save(out, format="PNG")
    return out


def _xdg_application_dirs() -> list[Path]:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs = [data_home, *data_dirs.split(":")]
    return [Path(d) / "applications" for d in dirs if d]


def discover_apps(dirs: list[Path] | None = None) -> list[dict[str, Any]]:
    """Read installed applications from XDG .desktop entries."""
    apps: dict[str, dict[str, Any]] = {}
    for directory in dirs if dirs is not None else _xdg_application_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.desktop")):
            app_id = path.relative_to(directory).with_suffix("").as_posix().replace("/", "-")
            if app_id in apps:  # earlier dirs take precedence per the XDG spec
                continue
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path, encoding="utf-8")
            except (configparser.Error, UnicodeDecodeError):
                continue
            if not parser.has_section("Desktop Entry"):
                continue
            entry = parser["Desktop Entry"]
            if entry.get("Type", "Application") != "Application":
                continue
            if entry.get("NoDisplay", "false").lower() == "true":
                continue
            if entry.get("Hidden", "false").lower() == "true":
                continue
            apps[app_id] = {
                "id": app_id,
                "name": entry.get("Name", app_id),
                "exec": entry.get("Exec", ""),
                "categories": [c for c in entry.get("Categories", "").split(";") if c],
            }
    return sorted(apps.values(), key=lambda a: a["name"].lower())


# --------------------------------------------------------------------------- #
# Server and tools
# --------------------------------------------------------------------------- #

mcp = MCPServer(
    SERVER_NAME,
    version=__version__,
    instructions=(
        "Control the Linux desktop. Start with list_windows, then get_window_state "
        "to read a window's elements before acting on them by index. Verify each "
        "action with a fresh get_window_state or screenshot."
    ),
)


@mcp.tool()
def list_apps() -> dict[str, Any]:
    """List installed desktop applications (from XDG .desktop entries)."""
    apps = discover_apps()
    return _audit("list_apps", {}, {"effect": "success", "count": len(apps), "apps": apps})


@mcp.tool()
def list_windows() -> dict[str, Any]:
    """List open, visible windows with their ids, titles and geometry."""
    windows = get_driver().list_windows()
    return _audit(
        "list_windows",
        {},
        {"effect": "success", "count": len(windows), "windows": [w.to_dict() for w in windows]},
    )


@mcp.tool()
def get_window_state(window_id: int) -> dict[str, Any]:
    """Get a window's element tree (buttons, fields, menus... via AT-SPI).

    Element indexes from this result are what click, type_text, scroll and
    screenshot_element take. Call it again after the UI changes.
    """
    driver = get_driver()
    state = _window_state(driver, window_id, acting=False)
    _remember(state)
    return _audit(
        "get_window_state",
        {"window_id": window_id},
        {
            "effect": "success",
            "window_id": state.window_id,
            "pid": state.pid,
            "source": state.source,
            "sensitive": state.sensitive,
            "sensitive_reasons": state.sensitive_reasons,
            "truncated": state.truncated,
            "tree_markdown": state.tree_markdown,
            "elements": [e.to_dict() for e in state.elements],
        },
    )


@mcp.tool()
def get_app_info(window_id: int) -> dict[str, Any]:
    """Get information about the application that owns a window."""
    driver = get_driver()
    window = _find_window(driver, window_id)
    windows = driver.list_windows()
    siblings = [
        {"window_id": w.window_id, "title": w.title}
        for w in windows
        if window.pid and w.pid == window.pid
    ]
    return _audit(
        "get_app_info",
        {"window_id": window_id},
        {
            "effect": "success",
            "app_id": window.app_id,
            "name": window.app or window.title,
            "pid": window.pid,
            "windows": siblings or [{"window_id": window.window_id, "title": window.title}],
        },
    )


@mcp.tool()
def click(
    window_id: int,
    element: int | None = None,
    x: int | None = None,
    y: int | None = None,
) -> dict[str, Any]:
    """Click an element by index, or click at absolute screen coordinates x, y.

    Give either `element` or both `x` and `y`.
    """
    driver = get_driver()
    if element is not None:
        if x is not None or y is not None:
            raise ToolError("Give either element or x/y, not both.")
        success = driver.click(_find_element(driver, window_id, element))
    elif x is not None and y is not None:
        window = _find_window(driver, window_id)
        if not (window.x <= x < window.x + window.width and window.y <= y < window.y + window.height):
            raise ToolError(f"Point ({x}, {y}) is outside window {window_id}.")
        _window_state(driver, window_id, acting=True)
        success = driver.click_coordinate(x, y)
    else:
        raise ToolError("Give an element index, or both x and y.")

    return _audit(
        "click",
        {"window_id": window_id, "element": element, "x": x, "y": y},
        {"effect": "confirmed" if success else "failed", "window_id": window_id},
    )


@mcp.tool()
def type_text(text: str, window_id: int, element: int | None = None) -> dict[str, Any]:
    """Type text into an element, or into the focused part of the window if no element is given."""
    driver = get_driver()
    if element is not None:
        target = _find_element(driver, window_id, element)
    else:
        target = _find_element(driver, window_id, 0)
        if not driver.focus_window(window_id):
            raise ToolError(f"Could not focus window {window_id}.")
    success = driver.type_text(text, target)
    return _audit(
        "type_text",
        {"text": text[:100], "window_id": window_id, "element": element},
        {
            "effect": "confirmed" if success else "failed",
            "characters_typed": len(text) if success else 0,
            "window_id": window_id,
        },
    )


@mcp.tool()
def press_key(keys: str, window_id: int | None = None) -> dict[str, Any]:
    """Press a key or combination in xdotool syntax, e.g. 'Return', 'ctrl+c', 'alt+F4'.

    If window_id is given, that window is focused first.
    """
    driver = get_driver()
    if window_id is not None:
        _window_state(driver, window_id, acting=True)
        if not driver.focus_window(window_id):
            raise ToolError(f"Could not focus window {window_id}.")
    else:
        focused = driver.get_focused_window()
        if focused is not None:
            _refuse_if_sensitive(driver.get_window_state(focused))
    success = driver.press_key(keys)
    return _audit(
        "press_key",
        {"keys": keys, "window_id": window_id},
        {"effect": "confirmed" if success else "failed", "keys": keys, "window_id": window_id},
    )


@mcp.tool()
def scroll(
    direction: Literal["up", "down", "left", "right"],
    window_id: int,
    amount: int = 3,
    element: int = 0,
) -> dict[str, Any]:
    """Scroll over an element (default: the whole window) by `amount` wheel steps (1-100)."""
    if not 1 <= amount <= 100:
        raise ToolError("amount must be between 1 and 100.")
    driver = get_driver()
    success = driver.scroll(direction, amount, _find_element(driver, window_id, element))
    return _audit(
        "scroll",
        {"direction": direction, "amount": amount, "window_id": window_id, "element": element},
        {
            "effect": "confirmed" if success else "failed",
            "direction": direction,
            "amount": amount,
            "window_id": window_id,
        },
    )


def _image_result(tool: str, args: dict[str, Any], path: Path) -> list[Any]:
    _audit(tool, args, {"effect": "success"})
    return [Image(path=path), json.dumps({"path": str(path), **args})]


@mcp.tool(structured_output=False)
def screenshot_desktop(
    x: int | None = None,
    y: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> list[Any]:
    """Screenshot the whole desktop, or a region if x, y, width and height are all given."""
    parts = (x, y, width, height)
    if any(p is not None for p in parts) and not all(p is not None for p in parts):
        raise ToolError("For a region, give all of x, y, width and height.")
    region = (x, y, width, height) if x is not None else None
    path = _capture(get_driver(), region, "desktop")  # type: ignore[arg-type]
    return _image_result("screenshot_desktop", {"region": region}, path)


@mcp.tool(structured_output=False)
def screenshot_window(window_id: int) -> list[Any]:
    """Screenshot a single window."""
    driver = get_driver()
    w = _find_window(driver, window_id)
    path = _capture(driver, (w.x, w.y, w.width, w.height), f"window_{window_id}")
    return _image_result("screenshot_window", {"window_id": window_id}, path)


@mcp.tool(structured_output=False)
def screenshot_element(window_id: int, element: int) -> list[Any]:
    """Screenshot a single UI element."""
    driver = get_driver()
    e = _find_element(driver, window_id, element, acting=False)
    path = _capture(driver, (e.x, e.y, e.width, e.height), f"element_{window_id}_{element}")
    return _image_result("screenshot_element", {"window_id": window_id, "element": element}, path)


def main() -> None:
    """Run the server over stdio."""
    logging.basicConfig(level=logging.INFO)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
