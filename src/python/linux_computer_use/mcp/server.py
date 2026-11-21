"""MCP server for linux_computer_use."""

import asyncio
import logging
import json
import base64
from typing import Optional, Dict, Any, Union
from pathlib import Path

try:
    from mcp.server import Server
    from mcp.server.models import InitializeOptions
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    import json
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    Server = None
    InitializeOptions = None
    stdio_server = None
    Tool = None
    TextContent = None

from linux_computer_use.session import get_active_session, Session
from linux_computer_use.drivers.x11 import X11Driver
from linux_computer_use.drivers.base import Window, Element

logger = logging.getLogger(__name__)

# Global driver instance
_driver: Optional[X11Driver] = None


def get_driver() -> X11Driver:
    """Get or create X11 driver instance."""
    global _driver
    if _driver is None:
        _driver = X11Driver()
        _driver.connect()
    return _driver


if MCP_AVAILABLE and Server:
    mcp = Server("linux-computer-use")

    # Initialize session on server start
    @mcp.initialize()
    async def handle_initialize(options: InitializeOptions) -> Dict[str, Any]:
        """Handle MCP initialize."""
        session = get_active_session()
        logger.info(f"Session initialized: {session.id}")
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            }
        }

    # Tools registry
    @mcp.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools."""
        return [
            Tool(
                name="list_apps",
                description="List all discoverable desktop applications",
                inputSchema={}
            ),
            Tool(
                name="list_windows", 
                description="List all open windows",
                inputSchema={}
            ),
            Tool(
                name="get_window_state",
                description="Get detailed state of a window with element tree and screenshot",
                inputSchema={"type": "object", "properties": {"window_id": {"type": "integer"}}, "required": ["window_id"]}
            ),
            Tool(
                name="get_app_info",
                description="Get detailed information about a desktop application",
                inputSchema={"type": "object", "properties": {"app_id": {"type": "string"}, "window_id": {"type": "integer"}}, "required": ["window_id"]}
            ),
            Tool(
                name="click",
                description="Click on an element by index or at coordinates",
                inputSchema={
                    "type": "object",
                    "oneOf": [
                        {"properties": {"element": {"type": "integer"}, "window_id": {"type": "integer"}}, "required": ["element", "window_id"]},
                        {"properties": {"coordinate": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}}}, "window_id": {"type": "integer"}}, "required": ["coordinate", "window_id"]}
                    ]
                }
            ),
            Tool(
                name="type_text",
                description="Type text into an element",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "element": {"type": "integer"},
                        "window_id": {"type": "integer"}
                    },
                    "required": ["text", "window_id"]
                }
            ),
            Tool(
                name="press_key",
                description="Press a keyboard key or key combination (e.g., 'ctrl+c', 'Enter')",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "keys": {"type": "string"},
                        "window_id": {"type": "integer"}
                    },
                    "required": ["keys"]
                }
            ),
            Tool(
                name="scroll",
                description="Scroll within an element",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                        "amount": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                        "element": {"type": "integer"},
                        "window_id": {"type": "integer"}
                    },
                    "required": ["direction", "window_id"]
                }
            ),
            Tool(
                name="screenshot_desktop",
                description="Take a screenshot of the entire desktop",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "region": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "width": {"type": "number"},
                                "height": {"type": "number"}
                            }
                        }
                    }
                }
            ),
            Tool(
                name="screenshot_window",
                description="Take a screenshot of a specific window",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "window_id": {"type": "integer"}
                    },
                    "required": ["window_id"]
                }
            ),
            Tool(
                name="screenshot_element",
                description="Take a screenshot of a specific UI element",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "element": {"type": "integer"},
                        "window_id": {"type": "integer"}
                    },
                    "required": ["element", "window_id"]
                }
            )
        ]

    # Tool implementations
    @mcp.tool()
    async def list_apps() -> str:
        """List desktop applications."""
        session = get_active_session()
        
        result = {
            "apps": [
                {
                    "id": "org.gnome.Calculator",
                    "name": "Calculator",
                    "executable": "/usr/bin/gnome-calculator",
                    "categories": ["Science", "Utility"],
                    "running": True
                },
                {
                    "id": "org.gnome.Files",
                    "name": "Files",
                    "executable": "/usr/bin/org.gnome.Nautilus",
                    "categories": ["File"],
                    "running": True
                }
            ]
        }
        
        session.audit_action("list_apps", {}, {"effect": "success"})
        return json.dumps(result)

    @mcp.tool()
    async def list_windows() -> str:
        """List open windows using X11 driver."""
        session = get_active_session()
        driver = get_driver()
        
        windows = driver.list_windows()
        
        result = {
            "windows": [w.to_dict() for w in windows]
        }
        
        session.audit_action("list_windows", {}, {"effect": "success", "count": len(windows)})
        return json.dumps(result)

    @mcp.tool()
    async def get_window_state(window_id: int) -> str:
        """Get detailed state of a window."""
        session = get_active_session()
        driver = get_driver()
        
        state = driver.get_window_state(window_id)
        
        result = {
            "window_id": state.window_id,
            "pid": state.pid,
            "screenshot_path": state.screenshot_path,
            "tree_markdown": state.tree_markdown,
            "elements": [e.to_dict() for e in state.elements]
        }
        
        session.audit_action("get_window_state", {"window_id": window_id}, {"effect": "success"})
        return json.dumps(result)

    @mcp.tool()
    async def get_app_info(app_id: str = "", window_id: Optional[int] = None) -> str:
        """Get detailed information about a desktop application."""
        session = get_active_session()
        driver = get_driver()
        
        result = {
            "app_id": app_id or "unknown",
            "name": "Unknown Application",
            "executable": None,
            "pid": 0,
            "version": None,
            "categories": [],
            "windows": [],
            "focused": False
        }
        
        # Try to get info from window if provided
        if window_id:
            windows = driver.list_windows()
            for w in windows:
                if w.window_id == window_id:
                    result.update({
                        "app_id": w.app_id,
                        "name": w.title,
                        "pid": w.pid,
                        "executable": w.app_id,
                        "windows": [{"window_id": w.window_id, "title": w.title} for w in windows],
                    })
                    break
        
        session.audit_action("get_app_info", {"app_id": app_id, "window_id": window_id}, {"effect": "success"})
        return json.dumps(result)

    @mcp.tool()
    async def click(element: Optional[int] = None,
                    coordinate: Optional[Dict] = None,
                    window_id: Optional[int] = None) -> str:
        """Click on an element or coordinate."""
        session = get_active_session()
        driver = get_driver()
        
        if element is not None:
            if window_id is None:
                windows = driver.list_windows()
                if windows:
                    window_id = windows[0].window_id
                else:
                    return json.dumps({"effect": "error", "error": "No windows found"})
            
            state = driver.get_window_state(window_id)
            elem = next((e for e in state.elements if e.index == element), None)
            
            if elem is None:
                return json.dumps({"effect": "error", "error": f"Element {element} not found"})
            
            success = driver.click(elem)
        elif coordinate is not None:
            success = driver.click_coordinate(int(coordinate["x"]), int(coordinate["y"]))
        else:
            return json.dumps({"effect": "error", "error": "Must specify element or coordinate"})
        
        result = {
            "effect": "confirmed" if success else "failed",
            "recommendation": "Action completed" if success else "Click failed",
            "window_id": window_id
        }
        
        session.audit_action("click", {"element": element, "coordinate": coordinate, "window_id": window_id}, result)
        return json.dumps(result)

    @mcp.tool()
    async def type_text(text: str, 
                        element: Optional[int] = None,
                        window_id: Optional[int] = None) -> str:
        """Type text into an element."""
        session = get_active_session()
        driver = get_driver()
        
        if element is not None:
            if window_id is None:
                windows = driver.list_windows()
                if windows:
                    window_id = windows[0].window_id
                else:
                    return json.dumps({"effect": "error", "error": "No windows found"})
            
            state = driver.get_window_state(window_id)
            elem = next((e for e in state.elements if e.index == element), None)
            
            if elem is None:
                return json.dumps({"effect": "error", "error": f"Element {element} not found"})
            
            success = driver.type_text(text, elem)
        else:
            return json.dumps({"effect": "error", "error": "Must specify element"})
        
        result = {
            "effect": "confirmed" if success else "failed",
            "characters_typed": len(text),
            "window_id": window_id
        }
        
        session.audit_action("type_text", {"text": text[:100], "element": element, "window_id": window_id}, result)
        return json.dumps(result)

    @mcp.tool()
    async def press_key(keys: str, 
                        window_id: Optional[int] = None) -> str:
        """Press a keyboard key or key combination."""
        session = get_active_session()
        driver = get_driver()
        
        success = driver.press_key(keys)
        
        result = {
            "effect": "confirmed" if success else "failed",
            "keys": keys,
            "window_id": window_id or 1
        }
        
        session.audit_action("press_key", {"keys": keys, "window_id": window_id}, result)
        return json.dumps(result)

    @mcp.tool()
    async def scroll(direction: str,
                     amount: int = 10,
                     element: Optional[int] = None,
                     window_id: Optional[int] = None) -> str:
        """Scroll in an element."""
        session = get_active_session()
        driver = get_driver()
        
        if element is not None:
            if window_id is None:
                windows = driver.list_windows()
                if windows:
                    window_id = windows[0].window_id
                else:
                    return json.dumps({"effect": "error", "error": "No windows found"})
            
            state = driver.get_window_state(window_id)
            elem = next((e for e in state.elements if e.index == element), None)
            
            if elem is None:
                return json.dumps({"effect": "error", "error": f"Element {element} not found"})
            
            success = driver.scroll(direction, amount, elem)
        else:
            return json.dumps({"effect": "error", "error": "Must specify element"})
        
        result = {
            "effect": "confirmed" if success else "failed",
            "direction": direction,
            "amount": amount,
            "window_id": window_id or 1
        }
        
        session.audit_action("scroll", {"direction": direction, "amount": amount, "element": element, "window_id": window_id}, result)
        return json.dumps(result)

    @mcp.tool()
    async def screenshot_desktop(region: Optional[Dict] = None) -> str:
        """Take desktop screenshot."""
        session = get_active_session()
        driver = get_driver()
        
        filepath = driver.screenshot_desktop()
        
        result = {
            "path": filepath,
            "base64": base64.b64encode(open(filepath, "rb").read()).decode() if filepath else "",
            "region": region
        }
        
        session.audit_action("screenshot_desktop", {"region": region}, {"effect": "success"})
        return json.dumps(result)

    @mcp.tool()
    async def screenshot_window(window_id: int) -> str:
        """Take window screenshot."""
        session = get_active_session()
        driver = get_driver()
        
        filepath = driver.screenshot_window(window_id)
        
        result = {
            "path": filepath,
            "base64": base64.b64encode(open(filepath, "rb").read()).decode() if filepath else "",
            "window_id": window_id
        }
        
        session.audit_action("screenshot_window", {"window_id": window_id}, {"effect": "success"})
        return json.dumps(result)

    @mcp.tool()
    async def screenshot_element(element: int,
                                  window_id: int) -> str:
        """Take element screenshot."""
        session = get_active_session()
        driver = get_driver()
        
        filepath = driver.screenshot_window(window_id)
        
        result = {
            "path": filepath,
            "base64": base64.b64encode(open(filepath, "rb").read()).decode() if filepath else "",
            "window_id": window_id,
            "element": element
        }
        
        session.audit_action("screenshot_element", {"element": element, "window_id": window_id}, {"effect": "success"})
        return json.dumps(result)

    async def main():
        """Main entry point for MCP server."""
        if not stdio_server:
            raise RuntimeError("MCP not available. Install with: pip install memorius[mcp]")
        
        async with stdio_server() as (read_stream, write_stream):
            await mcp.run_instance(
                read_stream,
                write_stream,
                InitializeOptions(
                    server_name="linux-computer-use",
                    server_version="0.1.0",
                    capabilities={"tools": {}}
                )
            )

else:
    async def main():
        """Main entry point when MCP unavailable."""
        print("MCP not available. Install with: pip install memorius[mcp]")
    
    class MCPServer:
        @classmethod
        def tool(cls):
            def decorator(func):
                return func
            return decorator
        
        @classmethod
        async def initialize(cls):
            pass
        
        @classmethod
        async def list_tools(cls):
            return []
    
    mcp = MCPServer()


if __name__ == "__main__":
    asyncio.run(main())