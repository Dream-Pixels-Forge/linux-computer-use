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
                        "coordinate": {
                            "type": "object",
                            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                        },
                        "window_id": {"type": "integer"}
                    },
                    "required": ["window_id"]
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
                    "required": ["text", "window_id"]
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
    """In-process access to the MCP server's tools for agent integrations.

    Calls the same tool functions the MCP server exposes, so adapters get the
    same checks (stale elements, sensitive windows) and real results. Tool
    errors come back as ``{"error": "..."}``.
    """

    def __init__(self) -> None:
        from linux_computer_use.session import get_active_session

        self.session = get_active_session()

    @staticmethod
    def _run(fn: Any, **kwargs: Any) -> dict[str, Any]:
        from mcp.server.mcpserver.exceptions import ToolError

        try:
            result: dict[str, Any] = fn(**kwargs)
        except ToolError as exc:
            return {"error": str(exc)}
        return result

    async def list_windows(self) -> dict[str, Any]:
        """List all open windows."""
        from linux_computer_use.mcp import server

        return self._run(server.list_windows)

    async def get_window_state(self, window_id: int) -> dict[str, Any]:
        """Get a window's element tree."""
        from linux_computer_use.mcp import server

        return self._run(server.get_window_state, window_id=window_id)

    async def click(self, element: int | None = None,
                    coordinate: dict[str, Any] | None = None,
                    window_id: int | None = None,
                    element_token: str | None = None) -> dict[str, Any]:
        """Click an element by index, or at coordinate {"x": .., "y": ..}."""
        from linux_computer_use.mcp import server

        if element_token is not None:
            return {"error": "element_token is not supported; use element and window_id"}
        if window_id is None:
            return {"error": "window_id is required"}
        x = y = None
        if coordinate is not None:
            x, y = int(coordinate["x"]), int(coordinate["y"])
        return self._run(server.click, window_id=window_id, element=element, x=x, y=y)

    async def type_text(self, text: str,
                        element: int | None = None,
                        window_id: int | None = None,
                        element_token: str | None = None) -> dict[str, Any]:
        """Type text into an element, or into the focused part of the window."""
        from linux_computer_use.mcp import server

        if element_token is not None:
            return {"error": "element_token is not supported; use element and window_id"}
        if window_id is None:
            return {"error": "window_id is required"}
        return self._run(server.type_text, text=text, window_id=window_id, element=element)

    async def screenshot_window(self, window_id: int) -> dict[str, Any]:
        """Screenshot a window, as a PNG path plus base64 data."""
        import base64
        import json
        from pathlib import Path

        from mcp.server.mcpserver.exceptions import ToolError

        from linux_computer_use.mcp import server

        try:
            _image, meta = server.screenshot_window(window_id=window_id)
        except ToolError as exc:
            return {"error": str(exc)}
        path = json.loads(meta)["path"]
        return {"path": path, "base64": base64.b64encode(Path(path).read_bytes()).decode()}


# Convenience function to get tool proxy
def get_tool_proxy() -> MCPToolProxy:
    """Get a tool proxy for MCP operations."""
    return MCPToolProxy()
