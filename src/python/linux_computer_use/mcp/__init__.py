"""MCP server implementation."""

# Lazy import to avoid circular dependency
_mcp_server = None

def get_mcp():
    """Get the MCP server instance."""
    global _mcp_server
    if _mcp_server is None:
        from linux_computer_use.mcp.server import mcp
        _mcp_server = mcp
    return _mcp_server

__all__ = ["get_mcp", "mcp"]

# Import mcp for backward compatibility
from linux_computer_use.mcp.server import mcp