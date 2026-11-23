#!/usr/bin/env python3
"""CLI interface for linux_computer_use."""

import argparse
import sys
from pathlib import Path

from linux_computer_use import __version__

try:
    from linux_computer_use.mcp.server import main as run_mcp_server
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
    subparsers.add_parser(
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
    subparsers.add_parser(
        "status",
        help="Show server status"
    )

    return parser


def start_mcp_server(port: int | None = None) -> None:
    """Start the MCP server over stdio."""
    if not MCP_AVAILABLE:
        print("MCP not available. Install with: pip install 'mcp>=2,<3'", file=sys.stderr)
        sys.exit(1)
    if port is not None:
        print("--port is not supported yet; using stdio.", file=sys.stderr)
    run_mcp_server()


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "start":
        start_mcp_server(args.port)
        return 0

    if args.command == "status":
        print("linux_computer_use server status:")
        print("  MCP: available" if MCP_AVAILABLE else "  MCP: not available")
        print(f"  Version: {__version__}")
        return 0

    if args.command == "list-windows":
        from linux_computer_use.drivers.x11 import X11Driver
        driver = X11Driver()
        driver.connect()
        windows = driver.list_windows()
        for w in windows:
            print(f"{w.window_id}\t{w.title}")
        return 0

    if args.command == "screenshot":
        from linux_computer_use.mcp.server import get_driver
        desktop_driver = get_driver()
        out = args.output
        if args.window is not None:
            path = desktop_driver.screenshot_window(args.window)
            if not path:
                print("Screenshot failed.", file=sys.stderr)
                return 1
        else:
            path = desktop_driver.screenshot_desktop()
            if not path:
                print("Screenshot failed.", file=sys.stderr)
                return 1
        if out is not None:
            from shutil import copyfile
            copyfile(path, out)
            print(out)
        else:
            print(path)
        return 0

    print(f"Command '{args.command}' not yet implemented", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
