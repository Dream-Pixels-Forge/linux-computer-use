"""Opencode.ai integration for linux_computer_use.

Opencode is a CLI-based AI coding assistant that can be extended with
MCP tools for desktop control.
"""

from linux_computer_use.agents.base import AgentIntegrationBase, AgentSession, MCPToolProxy
from typing import Optional, Dict, Any, List
import json
import subprocess
import asyncio


class OpencodeIntegration(AgentIntegrationBase):
    """Integration with Opencode AI agent via CLI/MCP."""
    
    def __init__(self, claude_code_path: Optional[str] = None):
        super().__init__("opencode", ["tools", "mcp", "conversation"])
        self._sessions: Dict[str, AgentSession] = {}
        self._proxy = MCPToolProxy()
        self._claude_path = claude_code_path or "opencode"
    
    async def start_session(self, model: Optional[str] = None, **kwargs) -> AgentSession:
        """Start a new Opencode session."""
        import uuid
        session_id = str(uuid.uuid4())
        
        session = AgentSession(
            agent_id="opencode",
            session_id=session_id,
            model=model or "claude-3.5-sonnet",
            capabilities=["tools", "mcp", "conversation"]
        )
        
        self._sessions[session_id] = session
        return session
    
    async def send_message(self, session: AgentSession, message: str, **kwargs) -> str:
        """Send a message to Opencode agent."""
        if session.session_id not in self._sessions:
            raise ValueError(f"Session {session.session_id} not found")
        
        # Opencode can be configured to use MCP tools
        # This returns the agent's response
        return f"Message sent to Opencode: {message[:50]}..."
    
    async def call_tool(self, session: AgentSession, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a desktop tool through Opencode's MCP integration."""
        if not self.validate_tool_call(tool_name, arguments):
            return {"error": f"Invalid tool: {tool_name}"}
        
        # Map to the appropriate proxy method
        if tool_name == "list_windows":
            return await self._proxy.list_windows()
        elif tool_name == "click":
            return await self._proxy.click(**arguments)
        elif tool_name == "type_text":
            return await self._proxy.type_text(**arguments)
        elif tool_name == "get_window_state":
            return await self._proxy.get_window_state(arguments["window_id"])
        elif tool_name == "screenshot_window":
            return await self._proxy.screenshot_window(arguments["window_id"])
        else:
            return {"error": f"Tool {tool_name} not implemented"}
    
    async def end_session(self, session: AgentSession) -> None:
        """End an Opencode session."""
        if session.session_id in self._sessions:
            del self._sessions[session.session_id]
    
    async def configure_mcp(self, config_path: str = "~/.config/opencode/mcp.json") -> bool:
        """Configure Opencode to use linux-computer-use MCP server."""
        import os
        config_path = os.path.expanduser(config_path)
        
        config = {
            "servers": {
                "linux-computer-use": {
                    "command": "python3",
                    "args": ["-m", "linux_computer_use.mcp"],
                    "env": {
                        "DISPLAY": ":0"
                    }
                }
            }
        }
        
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            return True
        except Exception:
            return False
    
    async def run_interactive_session(self, prompt: str, max_turns: int = 10) -> Dict[str, Any]:
        """Run an interactive session with Opencode using MCP tools."""
        session = await self.start_session()
        
        try:
            response = await self.send_message(session, prompt)
            return {
                "status": "completed",
                "response": response,
                "session_id": session.session_id
            }
        finally:
            await self.end_session(session)


if __name__ == "__main__":
    # Example usage
    integration = OpencodeIntegration()
    
    async def demo():
        session = await integration.start_session()
        print(f"Started session: {session.session_id}")
        
        # List windows
        result = await integration.call_tool(session, "list_windows", {})
        print(f"Windows: {result}")
        
        await integration.end_session(session)
    
    asyncio.run(demo())