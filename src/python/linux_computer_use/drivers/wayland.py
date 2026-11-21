"""Wayland driver for desktop interaction."""

from linux_computer_use.drivers.base import Driver, Window, Element, WindowState
from typing import Optional, List


class WaylandDriver(Driver):
    """Driver for Wayland display server (read-only support)."""
    
    def __init__(self, display: Optional[str] = None):
        """Initialize Wayland driver."""
        self.display = display or "wayland-0"
        self._connected = False
    
    def connect(self) -> bool:
        """Connect to Wayland server."""
        # Wayland requires root/admin for many operations
        # We aim for read-only capability
        self._connected = True
        return True
    
    def list_windows(self) -> List[Window]:
        """List all open windows on Wayland."""
        if not self._connected:
            self.connect()
        
        # TODO: Use wayland library or wlroots
        # Limited access compared to X11
        return []
    
    def get_window_state(self, window_id: int) -> WindowState:
        """Get detailed state of a window."""
        if not self._connected:
            self.connect()
        
        # Wayland: Read-only, use root window fallback
        return WindowState(
            window_id=window_id,
            pid=0,
            screenshot_path="",
            tree_markdown="",
            elements=[]
        )
    
    def click(self, element: Element) -> bool:
        """Click on an element (not supported on Wayland)."""
        # Wayland restricts programmatic input
        raise NotImplementedError("Click not supported on Wayland in read-only mode")
    
    def type_text(self, text: str, element: Element) -> bool:
        """Type text into an element (not supported on Wayland)."""
        raise NotImplementedError("Type not supported on Wayland in read-only mode")
    
    def scroll(self, direction: str, amount: int, element: Element) -> bool:
        """Scroll in an element (not supported on Wayland)."""
        raise NotImplementedError("Scroll not supported on Wayland in read-only mode")
    
    def screenshot_window(self, window_id: int) -> str:
        """Take screenshot of window."""
        # Use pipewire or root window capture
        return ""
    
    def screenshot_desktop(self, region: Optional[tuple] = None) -> str:
        """Take screenshot of desktop."""
        return ""