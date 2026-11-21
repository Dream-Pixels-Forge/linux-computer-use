"""X11 driver for desktop interaction."""

from linux_computer_use.drivers.base import Driver, Window, Element, WindowState, Result
from typing import Optional, List, Tuple
import subprocess
import tempfile
import os
import time
import json
from pathlib import Path


class X11Driver(Driver):
    """Driver for X11 display server using xdotool and scrot."""
    
    def __init__(self, display: Optional[str] = None):
        """Initialize X11 driver."""
        self.display = display or ":0"
        self._connected = False
        self._shot_dir: Optional[Path] = None
        self._shot_count = 0
    
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
    
    def list_windows(self) -> List[Window]:
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
            
            window_ids = [w for w in result.stdout.strip().split("\n") if w.isdigit()]
            
            for win_id in window_ids:
                win_id = int(win_id)
                
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
    
    def _get_window_geometry(self, window_id: int) -> Optional[dict]:
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

    def _get_window_name(self, window_id: int) -> Optional[str]:
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
        """Get detailed state of a window."""
        if not self._connected:
            self.connect()
        
        # Get geometry
        geom = self._get_window_geometry(window_id)
        
        # Get screenshot path
        screenshot_path = self.screenshot_window(window_id)
        
        # Build element tree (simplified for X11)
        elements = self._build_element_tree(window_id)
        tree_markdown = self._build_tree_markdown(elements)
        
        return WindowState(
            window_id=window_id,
            pid=geom.get("pid", 0) if geom else 0,
            screenshot_path=screenshot_path,
            tree_markdown=tree_markdown,
            elements=elements
        )
    
    def _build_element_tree(self, window_id: int) -> List[Element]:
        """Build element tree from window."""
        elements = []
        
        # For X11, we create a simplified tree
        # In production, this would integrate with AT-SPI
        geom = self._get_window_geometry(window_id)
        
        if geom:
            # Root window element
            elements.append(Element(
                index=0,
                role="window",
                name=self._get_window_name(window_id) or "Window",
                x=geom.get("x", 0),
                y=geom.get("y", 0),
                width=geom.get("width", 0),
                height=geom.get("height", 0),
                window_id=window_id
            ))
        
        return elements
    
    def _build_tree_markdown(self, elements: List[Element]) -> str:
        """Build markdown representation of element tree."""
        if not elements:
            return "No elements found"
        
        lines = ["# Element Tree", ""]
        for elem in elements:
            indent = "\t" * (len(elem.children) if elem.parent_index >= 0 else 0)
            lines.append(f"{indent}- [{elem.role}] {elem.name}")
            if elem.state:
                lines.append(f"{indent}  States: {', '.join(elem.state)}")
        
        return "\n".join(lines)
    
    def click(self, element: Element) -> bool:
        """Click on an element by coordinates."""
        try:
            subprocess.run(
                ["xdotool", "mousemove", 
                 str(element.x + element.width // 2),
                 str(element.y + element.height // 2),
                 "click", "1"],
                capture_output=True,
                timeout=5
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def click_coordinate(self, x: int, y: int) -> bool:
        """Click at specific coordinates."""
        try:
            subprocess.run(
                ["xdotool", "mousemove", str(x), str(y), "click", "1"],
                capture_output=True,
                timeout=5
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def type_text(self, text: str, element: Element) -> bool:
        """Type text into an element."""
        try:
            # Move to element first
            subprocess.run(
                ["xdotool", "mousemove",
                 str(element.x + element.width // 2),
                 str(element.y + element.height // 2)],
                capture_output=True,
                timeout=5
            )
            
            # Type the text
            subprocess.run(
                ["xdotool", "type", "--delay", "0", text],
                capture_output=True,
                timeout=10
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def press_key(self, keys: str, element: Optional[Element] = None) -> bool:
        """Press a keyboard key or key combination."""
        try:
            subprocess.run(
                ["xdotool", "key", keys],
                capture_output=True,
                timeout=5
            )
            return True
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

    def screenshot_desktop(self, region: Optional[Tuple[int, int, int, int]] = None) -> str:
        """Take screenshot of desktop."""
        return self._scrot("desktop")

    def get_focused_window(self) -> Optional[int]:
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