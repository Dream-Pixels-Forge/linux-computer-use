#!/usr/bin/env python3
"""CLI interface for linux_computer_use."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

try:
    from mcp.server.stdio import stdio_server
    from mcp.server.models import InitializeOptions
    from linux_computer_use.mcp.server import mcp
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        prog="linux-computer-use",
        description="Unified Linux desktop control layer for AI agents"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Start MCP server
    start_parser = subparsers.add_parser(
        "start", 
        help="Start MCP server"
    )
    start_parser.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        help="Port for WebSocket server (optional)"
    )
    
    # List windows
    list_parser = subparsers.add_parser(
        "list-windows",
        help="List open windows"
    )
    
    # Screenshot
    shot_parser = subparsers.add_parser(
        "screenshot",
        help="Take a screenshot"
    )
    shot_parser.add_argument(
        "--window", "-w",
        type=int,
        help="Window ID to screenshot"
    )
    shot_parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output file path"
    )
    
    # Status
    status_parser = subparsers.add_parser(
        "status",
        help="Show server status"
    )
    
    return parser


async def start_mcp_server(port: int | None = None):
    """Start the MCP server."""
    if not MCP_AVAILABLE:
        print("MCP not available. Install with: pip install memorius[mcp]")
        sys.exit(1)
    
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


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return 0
    
    if args.command == "start":
        asyncio.run(start_mcp_server(args.port))
        return 0
    
    if args.command == "status":
        print("linux_computer_use server status:")
        print("  MCP: available" if MCP_AVAILABLE else "  MCP: not available")
        print(f"  Version: 0.1.0")
        return 0
    
    if args.command == "list-windows":
        from linux_computer_use.drivers.x11 import X11Driver
        driver = X11Driver()
        driver.connect()
        windows = driver.list_windows()
        for w in windows:
            print(f"{w.window_id}\t{w.title}")
        return 0
    
    print(f"Command '{args.command}' not yet implemented", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())