"""Base driver interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class Element:
    """UI element representation."""
    index: int
    role: str
    name: str
    description: str = ""
    state: List[str] = field(default_factory=list)
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    parent_index: int = -1
    children: List[int] = field(default_factory=list)
    automation_id: str = ""
    class_name: str = ""
    window_id: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "index": self.index,
            "role": self.role,
            "name": self.name,
            "description": self.description,
            "state": self.state,
            "geometry": {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height
            },
            "parent_index": self.parent_index,
            "children": self.children,
            "automation_id": self.automation_id,
            "class_name": self.class_name,
            "window_id": self.window_id
        }


@dataclass
class Window:
    """Window representation."""
    window_id: int
    pid: int
    app_id: str
    title: str
    x: int
    y: int
    width: int
    height: int
    workspace: int
    visible: bool
    app: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "window_id": self.window_id,
            "pid": self.pid,
            "app_id": self.app_id,
            "title": self.title,
            "geometry": {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height
            },
            "workspace": self.workspace,
            "visible": self.visible,
            "app": self.app
        }


@dataclass
class WindowState:
    """Complete window state."""
    window_id: int
    pid: int
    screenshot_path: str
    tree_markdown: str
    elements: List[Element]
    raw_tree: Optional[Dict] = None


class Driver(ABC):
    """Abstract base class for desktop drivers."""
    
    @abstractmethod
    def connect(self) -> bool:
        """Connect to the display server."""
        pass
    
    @abstractmethod
    def list_windows(self) -> List[Window]:
        """List all open windows."""
        pass
    
    @abstractmethod
    def get_window_state(self, window_id: int) -> WindowState:
        """Get detailed state of a window."""
        pass
    
    @abstractmethod
    def click(self, element: Element) -> bool:
        """Click on an element."""
        pass
    
    @abstractmethod
    def type_text(self, text: str, element: Element) -> bool:
        """Type text into an element."""
        pass
    
    @abstractmethod
    def scroll(self, direction: str, amount: int, element: Element) -> bool:
        """Scroll in an element."""
        pass
    
    @abstractmethod
    def screenshot_window(self, window_id: int) -> str:
        """Take screenshot of window."""
        pass
    
    @abstractmethod
    def screenshot_desktop(self, region: Optional[tuple] = None) -> str:
        """Take screenshot of desktop."""
        pass


class Result:
    """Result of an operation."""
    def __init__(self, success: bool, effect: str = "", recommendation: str = ""):
        self.success = success
        self.effect = effect
        self.recommendation = recommendation
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "effect": self.effect,
            "recommendation": self.recommendation
        }