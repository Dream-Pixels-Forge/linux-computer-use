"""End-to-end test: AT-SPI element trees through the real MCP server.

Needs an X display, a D-Bus session with the AT-SPI bus, PyGObject in this
environment, and a Python with GTK 3 for the demo app (LCU_GTK_PYTHON,
default /usr/bin/python3). In CI:

    dbus-run-session -- xvfb-run -a pytest tests/integration
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from linux_computer_use.drivers.atspi import ATSPIDriver
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

GTK_PYTHON = os.environ.get("LCU_GTK_PYTHON", "/usr/bin/python3")
DEMO_APP = Path(__file__).parent / "apps" / "gtk_demo.py"


def _gtk_available() -> bool:
    if not Path(GTK_PYTHON).exists():
        return False
    check = "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk"
    return subprocess.run([GTK_PYTHON, "-c", check], capture_output=True, check=False).returncode == 0


pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY")
    or not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    or not shutil.which("xdotool")
    or not ATSPIDriver().available
    or not _gtk_available(),
    reason="needs X, a D-Bus session, xdotool, PyGObject/AT-SPI and GTK 3",
)


def _start_app(title: str, *extra: str) -> tuple[subprocess.Popen[bytes], int]:
    proc = subprocess.Popen(
        [GTK_PYTHON, str(DEMO_APP), title, *extra],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        found = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", f"^{title}$"],
            capture_output=True, text=True, check=False,
        ).stdout.split()
        if found:
            return proc, int(found[0])
        time.sleep(0.1)
    proc.kill()
    pytest.fail(f"{title} window did not appear")


@pytest.fixture
def demo() -> Iterator[int]:
    proc, window_id = _start_app("LCU Demo")
    yield window_id
    proc.kill()
    proc.wait()


@pytest.fixture
def login() -> Iterator[int]:
    proc, window_id = _start_app("LCU Login", "--password")
    yield window_id
    proc.kill()
    proc.wait()


def _server() -> Client:
    """A client for the real server over stdio (opened inside each test, since
    anyio cancel scopes can't span pytest-asyncio fixture setup and teardown)."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "linux_computer_use.mcp"], env=dict(os.environ)
    )
    return Client(params)


async def _state(client: Client, window_id: int) -> dict[str, Any]:
    """Read the window, waiting for the app to register on the AT-SPI bus."""
    for _ in range(50):
        result = await client.call_tool("get_window_state", {"window_id": window_id})
        assert not result.is_error, result.content
        data: dict[str, Any] = result.structured_content
        if data["source"] == "atspi" and len(data["elements"]) > 1:
            return data
        time.sleep(0.1)
    pytest.fail(f"no AT-SPI tree for window {window_id}: {data['tree_markdown']}")


def _find(state: dict[str, Any], role: str, name: str | None = None) -> dict[str, Any]:
    return next(
        e for e in state["elements"] if e["role"] == role and (name is None or e["name"] == name)
    )


async def _act(client: Client, tool: str, args: dict[str, Any]) -> None:
    result = await client.call_tool(tool, args)
    assert not result.is_error, result.content


async def test_tree_and_actions(demo: int) -> None:
    async with _server() as client:
        await _check_tree_and_actions(client, demo)


async def _check_tree_and_actions(client: Client, demo: int) -> None:
    state = await _state(client, demo)
    assert state["sensitive"] is False
    assert state["elements"][0]["role"] == "frame"
    assert '"Count" (click)' in state["tree_markdown"]
    button = _find(state, "push button", "Count")
    check = _find(state, "check box", "Subscribe")
    entry = _find(state, "text")
    label = _find(state, "label", "Clicks: 0")

    await _act(client, "click", {"window_id": demo, "element": button["index"]})
    await _act(client, "click", {"window_id": demo, "element": check["index"]})
    await _act(client, "type_text", {"window_id": demo, "element": entry["index"], "text": "Ada"})
    time.sleep(0.3)

    after = await _state(client, demo)
    assert _find(after, "label", "Clicks: 1")
    assert "checked" in _find(after, "check box", "Subscribe")["state"]
    assert _find(after, "text")["value"] == "Ada"

    # The label's index still points at "Clicks: 0" in our *first* snapshot, but
    # we re-read since, so acting on it now is fine; re-reading is what clients do.
    # Simulate a client acting on an outdated snapshot instead:
    await _act(client, "click", {"window_id": demo, "element": button["index"]})
    time.sleep(0.2)
    stale = await client.call_tool("click", {"window_id": demo, "element": label["index"]})
    assert stale.is_error
    assert "changed since get_window_state" in stale.content[0].text


async def test_password_window_is_read_only(login: int) -> None:
    async with _server() as client:
        await _check_password_window(client, login)


async def _check_password_window(client: Client, login: int) -> None:
    state = await _state(client, login)
    assert state["sensitive"] is True
    assert any("password field" in r for r in state["sensitive_reasons"])
    password = _find(state, "password text")
    assert password["value"] is None

    refused = await client.call_tool(
        "type_text", {"window_id": login, "element": password["index"], "text": "hunter2"}
    )
    assert refused.is_error
    assert "password field" in refused.content[0].text

    button = _find(state, "push button", "Count")
    refused = await client.call_tool("click", {"window_id": login, "element": button["index"]})
    assert refused.is_error
