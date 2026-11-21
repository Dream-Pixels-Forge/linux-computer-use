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
    
    def connect(self) -> bool:
        """Connect to X11 server."""
        try:
            # Test X11 connection
            result = subprocess.run(
                ["xdotool", "getmwindowsize", "--shell"],
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
            
            geom = {}
            for line in result.stdout.split("\n"):
                if line.startswith("X="):
                    geom["x"] = int(line.split("=")[1])
                elif line.startswith("Y="):
                    geom["y"] = int(line.split("=")[1])
                elif line.startswith("W="):
                    geom["width"] = int(line.split("=")[1])
                elif line.startswith("H="):
                    geom["height"] = int(line.split("=")[1])
            
            return geom if geom else None
            
        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
            return None
    
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
        """Scroll in an element."""
        try:
            # Move to element first
            subprocess.run(
                ["xdotool", "mousemove",
                 str(element.x + element.width // 2),
                 str(element.y + element.height // 2)],
                capture_output=True,
                timeout=5
            )
            
            # Scroll
            if direction == "up":
                args = ["xdotool", "key", "ctrl+up"]
            elif direction == "down":
                args = ["xdotool", "key", "ctrl+down"]
            elif direction == "left":
                args = ["xdotool", "key", "ctrl+left"]
            else:  # right
                args = ["xdotool", "key", "ctrl+right"]
            
            for _ in range(max(1, amount // 100)):
                subprocess.run(args, capture_output=True, timeout=5)
            
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def screenshot_window(self, window_id: int) -> str:
        """Take screenshot of window."""
        temp_dir = Path(tempfile.gettempdir()) / f"linux-computer-use-{window_id}"
        temp_dir.mkdir(exist_ok=True)
        
        filepath = temp_dir / f"window_{window_id}.png"
        
        try:
            # Use scrot for screenshot
            result = subprocess.run(
                ["scrot", str(filepath)],
                capture_output=True,
                timeout=10
            )
            
            if result.returncode == 0 and filepath.exists():
                return str(filepath)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        return ""
    
    def screenshot_desktop(self, region: Optional[Tuple[int, int, int, int]] = None) -> str:
        """Take screenshot of desktop."""
        temp_dir = Path(tempfile.gettempdir()) / "linux-computer-use-desktop"
        temp_dir.mkdir(exist_ok=True)
        
        filepath = temp_dir / "desktop.png"
        
        try:
            # Use scrot for screenshot
            result = subprocess.run(
                ["scrot", str(filepath)],
                capture_output=True,
                timeout=10
            )
            
            if result.returncode == 0 and filepath.exists():
                return str(filepath)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        return ""
    
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
        """Focus a window."""
        try:
            result = subprocess.run(
                ["xdotool", "windowactivate", str(window_id)],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False