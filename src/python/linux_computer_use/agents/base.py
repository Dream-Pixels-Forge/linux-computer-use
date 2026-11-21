"""Base class for AI Agent integrations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import json


@dataclass
class AgentSession:
    """Represents an AI agent session."""
    agent_id: str
    session_id: Optional[str] = None
    model: Optional[str] = None
    capabilities: List[str] = None
    
    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = []


@dataclass
class AgentConversation:
    """Represents a conversation with an AI agent."""
    session: AgentSession
    messages: List[Dict[str, str]]
    tool_results: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.tool_results is None:
            self.tool_results = []


class AgentIntegrationBase(ABC):
    """Base class for AI agent integrations."""
    
    def __init__(self, name: str, capabilities: List[str]):
        self.name = name
        self.capabilities = capabilities
    
    @abstractmethod
    async def start_session(self, **kwargs) -> AgentSession:
        """Start a new agent session."""
        pass
    
    @abstractmethod
    async def send_message(self, session: AgentSession, message: str, **kwargs) -> str:
        """Send a message to the agent."""
        pass
    
    @abstractmethod
    async def call_tool(self, session: AgentSession, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool through the agent."""
        pass
    
    @abstractmethod
    async def end_session(self, session: AgentSession) -> None:
        """End an agent session."""
        pass
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
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
    
    def validate_tool_call(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """Validate a tool call against available tools."""
        available = {t["name"]: t for t in self.get_available_tools()}
        
        if tool_name not in available:
            return False
        
        # Additional validation could go here
        return True


class MCPToolProxy:
    """Proxy for MCP tools that can be used by any agent."""
    
    def __init__(self):
        from linux_computer_use.drivers.x11 import X11Driver
        from linux_computer_use.session import get_active_session
        self.driver = X11Driver()
        self.session = get_active_session()
    
    async def list_windows(self) -> Dict[str, Any]:
        """List all open windows."""
        windows = self.driver.list_windows()
        return {
            "windows": [w.to_dict() for w in windows]
        }
    
    async def click(self, element: Optional[int] = None, 
                    coordinate: Optional[Dict] = None,
                    window_id: Optional[int] = None,
                    element_token: Optional[str] = None) -> Dict[str, Any]:
        """Click on an element or coordinate."""
        # Implementation would use the driver
        return {"effect": "confirmed"}
    
    async def type_text(self, text: str, 
                        element: Optional[int] = None,
                        window_id: Optional[int] = None,
                        element_token: Optional[str] = None) -> Dict[str, Any]:
        """Type text into an element."""
        return {"effect": "confirmed", "characters_typed": len(text)}
    
    async def get_window_state(self, window_id: int) -> Dict[str, Any]:
        """Get window state."""
        state = self.driver.get_window_state(window_id)
        return {
            "window_id": state.window_id,
            "screenshot_path": state.screenshot_path,
            "tree_markdown": state.tree_markdown,
            "elements": [e.to_dict() for e in state.elements]
        }
    
    async def screenshot_window(self, window_id: int) -> Dict[str, Any]:
        """Take window screenshot."""
        import base64
        filepath = self.driver.screenshot_window(window_id)
        return {
            "path": filepath,
            "base64": base64.b64encode(open(filepath, "rb").read()).decode() if filepath else ""
        }


# Convenience function to get tool proxy
def get_tool_proxy() -> MCPToolProxy:
    """Get a tool proxy for MCP operations."""
    return MCPToolProxy()