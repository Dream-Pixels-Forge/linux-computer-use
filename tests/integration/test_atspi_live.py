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
GTK4_APP = Path(__file__).parent / "apps" / "gtk4_demo.py"


def _gtk_available(version: str = "3.0") -> bool:
    if not Path(GTK_PYTHON).exists():
        return False
    check = f"import gi; gi.require_version('Gtk', '{version}'); from gi.repository import Gtk"
    return subprocess.run([GTK_PYTHON, "-c", check], capture_output=True, check=False).returncode == 0


pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY")
    or not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    or not shutil.which("xdotool")
    or not ATSPIDriver().available
    or not _gtk_available(),
    reason="needs X, a D-Bus session, xdotool, PyGObject/AT-SPI and GTK 3",
)


def _start_app(
    title: str, *extra: str, app: Path = DEMO_APP
) -> tuple[subprocess.Popen[bytes], int]:
    proc = subprocess.Popen(
        [GTK_PYTHON, str(app), title, *extra],
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
def long_list() -> Iterator[int]:
    proc, window_id = _start_app("LCU List", "--rows", "500")
    yield window_id
    proc.kill()
    proc.wait()


@pytest.fixture
def gtk4_moved() -> Iterator[int]:
    if not _gtk_available("4.0"):
        pytest.skip("needs GTK 4 (gir1.2-gtk-4.0)")
    proc, window_id = _start_app("LCU GTK4", app=GTK4_APP)
    # GTK 4 can't place its own window; move it away from 0,0 so wrong
    # (screen 0,0) positions can't pass by accident.
    subprocess.run(["xdotool", "windowmove", "--sync", str(window_id), "300", "200"], check=True)
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

    for tool, args in (("screenshot_desktop", {}), ("screenshot_window", {"window_id": login})):
        refused = await client.call_tool(tool, args)
        assert refused.is_error, tool
        assert "password field" in refused.content[0].text


async def test_long_list_shows_only_visible_rows_and_scrolls(long_list: int) -> None:
    async with _server() as client:
        await _check_long_list(client, long_list)


async def _check_long_list(client: Client, window_id: int) -> None:
    state = await _state(client, window_id)
    rows = [e for e in state["elements"] if e["name"].startswith("Row ")]
    assert 0 < len(rows) < 50, len(rows)  # only what fits on screen, not all 500
    assert not state["truncated"]
    assert _find(state, "push button", "Row 0")
    first_rows = {e["name"] for e in rows}

    # Rows below the fold appear after scrolling, and can then be clicked.
    scroller = next(e for e in state["elements"] if e["role"] == "scroll pane")
    await _act(client, "scroll", {
        "window_id": window_id, "direction": "down", "amount": 10, "element": scroller["index"],
    })
    time.sleep(0.3)
    scrolled = await _state(client, window_id)
    later = [e for e in scrolled["elements"] if e["name"].startswith("Row ")]
    new_rows = [e for e in later if e["name"] not in first_rows]
    assert new_rows, "scrolling revealed no new rows"

    target = new_rows[0]
    await _act(client, "click", {"window_id": window_id, "element": target["index"]})
    time.sleep(0.2)
    picked = await _state(client, window_id)
    assert _find(picked, "label", f"Picked {target['name'].split()[1]}")


async def test_gtk4_positions_are_on_screen_and_clickable(gtk4_moved: int) -> None:
    async with _server() as client:
        await _check_gtk4_positions(client, gtk4_moved)


async def _check_gtk4_positions(client: Client, window_id: int) -> None:
    state = await _state(client, window_id)
    window = state["elements"][0]["geometry"]
    assert (window["x"], window["y"]) == (300, 200)
    button = _find(state, "push button", "Count")["geometry"]
    # Inside the window, not at screen 0,0 as GTK 4 reports it.
    assert window["x"] <= button["x"] < window["x"] + window["width"]
    assert window["y"] <= button["y"] < window["y"] + window["height"]

    # A click at the reported position must hit the button.
    x, y = button["x"] + button["width"] // 2, button["y"] + button["height"] // 2
    await _act(client, "click", {"window_id": window_id, "x": x, "y": y})
    time.sleep(0.3)
    after = await _state(client, window_id)
    assert _find(after, "label", "Clicks: 1")
