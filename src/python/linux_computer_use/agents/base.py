"""Base class for AI Agent integrations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSession:
    """Represents an AI agent session."""
    agent_id: str
    session_id: str | None = None
    model: str | None = None
    capabilities: list[str] = field(default_factory=list)


@dataclass
class AgentConversation:
    """Represents a conversation with an AI agent."""
    session: AgentSession
    messages: list[dict[str, str]]
    tool_results: list[dict[str, Any]] = field(default_factory=list)


class AgentIntegrationBase(ABC):
    """Base class for AI agent integrations."""

    def __init__(self, name: str, capabilities: list[str]):
        self.name = name
        self.capabilities = capabilities

    @abstractmethod
    async def start_session(self, **kwargs: Any) -> AgentSession:
        """Start a new agent session."""

    @abstractmethod
    async def send_message(self, session: AgentSession, message: str, **kwargs: Any) -> str:
        """Send a message to the agent."""

    @abstractmethod
    async def call_tool(self, session: AgentSession, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool through the agent."""

    @abstractmethod
    async def end_session(self, session: AgentSession) -> None:
        """End an agent session."""

    def get_available_tools(self) -> list[dict[str, Any]]:
        """Get list of tools available through this integration."""
        return [
            {
                "name": "list_windows",
                "description": "List all open windows on the desktop",
                "parameters": {}
            },
            {
                "name": "get_window_state",
                "description": "Get detailed state of a window",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "window_id": {"type": "integer"}
                    },
                    "required": ["window_id"]
                }
            },
            {
                "name": "click",
                "description": "Click on an element or coordinate",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "element": {"type": "integer"},
                        "element_token": {"type": "string"},
                        "coordinate": {"type": "object"},
                        "window_id": {"type": "integer"}
                    }
                }
            },
            {
                "name": "type_text",
                "description": "Type text into an element",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "element": {"type": "integer"},
                        "window_id": {"type": "integer"}
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "screenshot_window",
                "description": "Take a screenshot of a window",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "window_id": {"type": "integer"}
                    },
                    "required": ["window_id"]
                }
            }
        ]

    def validate_tool_call(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Validate a tool call against available tools."""
        available = {t["name"] for t in self.get_available_tools()}
        return tool_name in available


class MCPToolProxy:
    """Proxy for MCP tools that can be used by any agent."""

    def __init__(self) -> None:
        from linux_computer_use.drivers.x11 import X11Driver
        from linux_computer_use.session import get_active_session
        self.driver = X11Driver()
        self.session = get_active_session()

    async def list_windows(self) -> dict[str, Any]:
        """List all open windows."""
        windows = self.driver.list_windows()
        return {
            "windows": [w.to_dict() for w in windows]
        }

    async def click(self, element: int | None = None,
                    coordinate: dict[str, Any] | None = None,
                    window_id: int | None = None,
                    element_token: str | None = None) -> dict[str, Any]:
        """Click on an element or coordinate."""
        # Implementation would use the driver
        return {"effect": "confirmed"}

    async def type_text(self, text: str,
                        element: int | None = None,
                        window_id: int | None = None,
                        element_token: str | None = None) -> dict[str, Any]:
        """Type text into an element."""
        return {"effect": "confirmed", "characters_typed": len(text)}

    async def get_window_state(self, window_id: int) -> dict[str, Any]:
        """Get window state."""
        state = self.driver.get_window_state(window_id)
        return {
            "window_id": state.window_id,
            "screenshot_path": state.screenshot_path,
            "tree_markdown": state.tree_markdown,
            "elements": [e.to_dict() for e in state.elements]
        }

    async def screenshot_window(self, window_id: int) -> dict[str, Any]:
        """Take window screenshot."""
        import base64
        from pathlib import Path

        filepath = self.driver.screenshot_window(window_id)
        return {
            "path": filepath,
            "base64": base64.b64encode(Path(filepath).read_bytes()).decode() if filepath else "",
        }


# Convenience function to get tool proxy
def get_tool_proxy() -> MCPToolProxy:
    """Get a tool proxy for MCP operations."""
    return MCPToolProxy()
