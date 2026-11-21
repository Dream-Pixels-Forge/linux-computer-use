"""Base driver interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Element:
    """UI element representation."""
    index: int
    role: str
    name: str
    description: str = ""
    state: list[str] = field(default_factory=list)
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    parent_index: int = -1
    children: list[int] = field(default_factory=list)
    automation_id: str = ""
    class_name: str = ""
    window_id: int = 0
    actions: list[str] = field(default_factory=list)
    #: Current text of editable fields (never read for password fields).
    value: str | None = None

    def to_dict(self) -> dict[str, Any]:
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
            "window_id": self.window_id,
            "actions": self.actions,
            "value": self.value,
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

    def to_dict(self) -> dict[str, Any]:
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
    elements: list[Element]
    raw_tree: dict[str, Any] | None = None
    #: "atspi" when the tree came from the accessibility bus, "x11" for the
    #: window-outline fallback.
    source: str = "x11"
    #: True when the window contains a password field or similar secret input.
    sensitive: bool = False
    sensitive_reasons: list[str] = field(default_factory=list)
    truncated: bool = False


class Driver(ABC):
    """Abstract base class for desktop drivers."""

    @abstractmethod
    def connect(self) -> bool:
        """Connect to the display server."""

    @abstractmethod
    def list_windows(self) -> list[Window]:
        """List all open windows."""

    @abstractmethod
    def get_window_state(self, window_id: int) -> WindowState:
        """Get detailed state of a window."""

    @abstractmethod
    def click(self, element: Element) -> bool:
        """Click on an element."""

    @abstractmethod
    def type_text(self, text: str, element: Element) -> bool:
        """Type text into an element."""

    @abstractmethod
    def scroll(self, direction: str, amount: int, element: Element) -> bool:
        """Scroll in an element."""

    @abstractmethod
    def screenshot_window(self, window_id: int) -> str:
        """Take screenshot of window."""

    @abstractmethod
    def screenshot_desktop(self, region: tuple[int, int, int, int] | None = None) -> str:
        """Take screenshot of desktop."""


class Result:
    """Result of an operation."""
    def __init__(self, success: bool, effect: str = "", recommendation: str = ""):
        self.success = success
        self.effect = effect
        self.recommendation = recommendation

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "effect": self.effect,
            "recommendation": self.recommendation
        }
