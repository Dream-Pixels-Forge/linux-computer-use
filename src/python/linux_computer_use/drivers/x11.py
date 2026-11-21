"""X11 driver for desktop interaction."""

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from linux_computer_use.drivers.atspi import ATSPIDriver
from linux_computer_use.drivers.base import Driver, Element, Window, WindowState


class X11Driver(Driver):
    """Driver for X11 display server using xdotool and scrot."""

    def __init__(self, display: str | None = None):
        """Initialize X11 driver."""
        self.display = display or ":0"
        self._connected = False
        self._shot_dir: Path | None = None
        self._shot_count = 0
        self.atspi = ATSPIDriver()
        # Accessibles from the most recent tree read, keyed by (window_id, index),
        # so actions can use AT-SPI on exactly the element the caller saw.
        self._accessibles: dict[tuple[int, int], Any] = {}

    def connect(self) -> bool:
        """Connect to X11 server."""
        try:
            # Test X11 connection
            result = subprocess.run(
                ["xdotool", "getdisplaygeometry"],
                capture_output=True,
                text=True,
                timeout=5
            )
            self._connected = result.returncode == 0
            return self._connected
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self._connected = False
            return False

    def list_windows(self) -> list[Window]:
        """List all open windows on X11."""
        if not self._connected:
            self.connect()

        windows = []

        try:
            # Get window IDs
            result = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--name", ""],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return []

            window_ids = [int(w) for w in result.stdout.split() if w.isdigit()]

            for win_id in window_ids:

                # Get window geometry
                geom = self._get_window_geometry(win_id)

                # Get window name
                name = self._get_window_name(win_id)

                windows.append(Window(
                    window_id=win_id,
                    pid=geom.get("pid", 0) if geom else 0,
                    app_id="",
                    title=name or "Unknown",
                    x=geom.get("x", 0) if geom else 0,
                    y=geom.get("y", 0) if geom else 0,
                    width=geom.get("width", 0) if geom else 0,
                    height=geom.get("height", 0) if geom else 0,
                    workspace=0,
                    visible=True,
                    app=""
                ))

        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return windows

    def _get_window_geometry(self, window_id: int) -> dict[str, int] | None:
        """Get window geometry using xdotool."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", str(window_id)],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                return None

            fields = dict(
                line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
            )
            keys = {"X": "x", "Y": "y", "WIDTH": "width", "HEIGHT": "height"}
            geom = {name: int(fields[key]) for key, name in keys.items() if key in fields}
            pid = self._get_window_pid(window_id)
            if geom and pid:
                geom["pid"] = pid

            return geom if geom else None

        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
            return None

    def _get_window_pid(self, window_id: int) -> int:
        """Get the PID that owns a window (0 if unknown)."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowpid", str(window_id)],
                capture_output=True,
                text=True,
                timeout=5
            )
            out = result.stdout.strip()
            return int(out) if result.returncode == 0 and out.isdigit() else 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return 0

    def _get_window_name(self, window_id: int) -> str | None:
        """Get window name."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowname", str(window_id)],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                return result.stdout.strip() or None
            return None

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def get_window_state(self, window_id: int) -> WindowState:
        """Read a window's element tree.

        Uses the AT-SPI accessibility tree when the app publishes one, and
        falls back to a single element for the window itself.
        """
        if not self._connected:
            self.connect()

        geom = self._get_window_geometry(window_id) or {}
        pid = geom.get("pid", 0)
        title = self._get_window_name(window_id) or ""
        rect = (
            (geom["x"], geom["y"], geom["width"], geom["height"])
            if {"x", "y", "width", "height"} <= geom.keys()
            else None
        )

        for key in [k for k in self._accessibles if k[0] == window_id]:
            del self._accessibles[key]

        root = self.atspi.find_window(pid, title, rect)
        if root is not None:
            tree = self.atspi.read_tree(root, window_id)
            if tree.elements:
                for element, accessible in zip(tree.elements, tree.accessibles, strict=True):
                    self._accessibles[(window_id, element.index)] = accessible
                return WindowState(
                    window_id=window_id,
                    pid=pid,
                    screenshot_path="",
                    tree_markdown=tree.to_markdown(),
                    elements=tree.elements,
                    source="atspi",
                    sensitive=tree.sensitive,
                    sensitive_reasons=tree.sensitive_reasons,
                    truncated=tree.truncated,
                )

        elements = []
        if rect is not None:
            elements.append(Element(
                index=0, role="window", name=title or "Window",
                x=rect[0], y=rect[1], width=rect[2], height=rect[3],
                window_id=window_id,
            ))
        markdown = (
            f'- [0] window "{title}"\n'
            "(No accessibility tree: the app does not publish one over AT-SPI, "
            "or AT-SPI is unavailable. Use coordinates and screenshots.)"
            if elements else "No elements found"
        )
        return WindowState(
            window_id=window_id,
            pid=pid,
            screenshot_path="",
            tree_markdown=markdown,
            elements=elements,
            source="x11",
        )

    def click(self, element: Element) -> bool:
        """Click an element.

        Prefers the element's accessible click/press action (works even when
        the element is covered), otherwise clicks the centre of its bounds.
        """
        accessible = self._accessibles.get((element.window_id, element.index))
        if accessible is not None and self.atspi.do_click_action(accessible):
            return True
        if element.width <= 0 or element.height <= 0:
            return False
        return self.click_coordinate(
            element.x + element.width // 2, element.y + element.height // 2
        )

    def click_coordinate(self, x: int, y: int) -> bool:
        """Click at specific coordinates."""
        try:
            result = subprocess.run(
                ["xdotool", "mousemove", str(x), str(y), "click", "1"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def type_text(self, text: str, element: Element) -> bool:
        """Focus an element, then type text into it.

        Index 0 is the window itself: typing goes to whatever has focus there.
        """
        if element.index != 0:
            accessible = self._accessibles.get((element.window_id, element.index))
            focused = accessible is not None and self.atspi.grab_focus(accessible)
            if not focused and not self.click(element):
                return False
        try:
            result = subprocess.run(
                ["xdotool", "type", "--delay", "0", "--", text],
                capture_output=True,
                timeout=30
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def press_key(self, keys: str, element: Element | None = None) -> bool:
        """Press keys in xdotool syntax; space-separated keys are pressed in order."""
        sequence = keys.split()
        if not sequence:
            return False
        try:
            result = subprocess.run(
                ["xdotool", "key", "--", *sequence],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def scroll(self, direction: str, amount: int, element: Element) -> bool:
        """Scroll over an element with mouse-wheel clicks (X11 buttons 4-7)."""
        button = {"up": "4", "down": "5", "left": "6", "right": "7"}.get(direction)
        if button is None:
            return False
        try:
            result = subprocess.run(
                ["xdotool", "mousemove",
                 str(element.x + element.width // 2),
                 str(element.y + element.height // 2),
                 "click", "--repeat", str(max(1, amount)), button],
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _scrot(self, name: str) -> str:
        """Capture the screen with scrot into a fresh file in a private temp dir.

        scrot never overwrites: if the target exists it saves under a new name
        (``name_000.png``), so every capture must use a path that does not exist yet.
        """
        if self._shot_dir is None:
            self._shot_dir = Path(tempfile.mkdtemp(prefix="linux-computer-use-"))
        self._shot_count += 1
        filepath = self._shot_dir / f"{name}_{self._shot_count}.png"
        try:
            result = subprocess.run(
                ["scrot", str(filepath)],
                capture_output=True,
                timeout=10
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""
        return str(filepath) if result.returncode == 0 and filepath.exists() else ""

    def screenshot_window(self, window_id: int) -> str:
        """Take screenshot of the screen (callers crop to the window geometry)."""
        return self._scrot(f"window_{window_id}")

    def screenshot_desktop(self, region: tuple[int, int, int, int] | None = None) -> str:
        """Take screenshot of desktop."""
        return self._scrot("desktop")

    def get_focused_window(self) -> int | None:
        """Get the currently focused window."""
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0 and result.stdout.strip().isdigit():
                return int(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return None

    def focus_window(self, window_id: int) -> bool:
        """Focus a window.

        Tries ``windowactivate`` (asks the window manager, raises the window)
        and falls back to ``windowfocus`` (sets X input focus directly), which
        also works when no EWMH window manager is running.
        """
        for command in ("windowactivate", "windowfocus"):
            try:
                result = subprocess.run(
                    ["xdotool", command, "--sync", str(window_id)],
                    capture_output=True,
                    timeout=5
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
            if result.returncode == 0:
                return True
        return False
