"""End-to-end test: the Wayland driver, through the real MCP server.

Needs a Wayland compositor (WAYLAND_DISPLAY), a D-Bus session with the AT-SPI
bus, PyGObject here, and a Python with GTK 3 and GTK 4 for the demo apps
(LCU_GTK_PYTHON, default /usr/bin/python3). In CI, inside dbus-run-session:

    weston --backend=headless --socket=wayland-1 &
    WAYLAND_DISPLAY=wayland-1 pytest tests/integration/test_wayland_live.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from linux_computer_use.drivers.atspi import ATSPIDriver
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

GTK_PYTHON = os.environ.get("LCU_GTK_PYTHON", "/usr/bin/python3")
APPS = Path(__file__).parent / "apps"


def _gtk(version: str) -> bool:
    if not Path(GTK_PYTHON).exists():
        return False
    check = f"import gi; gi.require_version('Gtk', '{version}'); from gi.repository import Gtk"
    return subprocess.run([GTK_PYTHON, "-c", check], capture_output=True, check=False).returncode == 0


pytestmark = pytest.mark.skipif(
    not os.environ.get("WAYLAND_DISPLAY")
    or not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    or not ATSPIDriver().available
    or not _gtk("3.0"),
    reason="needs a Wayland compositor, a D-Bus session, PyGObject/AT-SPI and GTK",
)

TOOLKITS = {
    "gtk3": (APPS / "gtk_demo.py", "3.0"),
    "gtk4": (APPS / "gtk4_demo.py", "4.0"),
}


def _env() -> dict[str, str]:
    env = dict(os.environ, GDK_BACKEND="wayland")
    env.pop("DISPLAY", None)  # make sure nothing silently falls back to X11
    return env


def _launch(app: Path, title: str, *extra: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [GTK_PYTHON, str(app), title, *extra],
        env=_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@pytest.fixture(params=sorted(TOOLKITS))
def demo(request: pytest.FixtureRequest) -> Iterator[str]:
    app, version = TOOLKITS[request.param]
    if not _gtk(version):
        pytest.skip(f"needs GTK {version}")
    title = f"LCU Wayland {request.param}"
    proc = _launch(app, title)
    yield title
    proc.kill()
    proc.wait()


@pytest.fixture
def login() -> Iterator[str]:
    title = "LCU Wayland Login"
    proc = _launch(APPS / "gtk_demo.py", title, "--password")
    yield title
    proc.kill()
    proc.wait()


def _server() -> Client:
    env = _env()
    env.pop("LCU_DRIVER", None)  # the Wayland driver must be chosen automatically
    return Client(StdioServerParameters(
        command=sys.executable, args=["-m", "linux_computer_use.mcp"], env=env,
    ))


async def _call(client: Client, tool: str, args: dict[str, Any] | None = None) -> Any:
    result = await client.call_tool(tool, args or {})
    assert not result.is_error, result.content
    return result.structured_content


async def _refused(client: Client, tool: str, args: dict[str, Any]) -> str:
    result = await client.call_tool(tool, args)
    assert result.is_error, f"{tool} should be refused on Wayland"
    text: str = result.content[0].text
    return text


async def _window(client: Client, title: str) -> int:
    for _ in range(100):
        windows = (await _call(client, "list_windows"))["windows"]
        match = [w for w in windows if w["title"] == title]
        if match:
            return int(match[0]["window_id"])
        await asyncio.sleep(0.1)
    pytest.fail(f"{title} never appeared in list_windows")


async def _state(client: Client, window_id: int) -> dict[str, Any]:
    for _ in range(50):
        state: dict[str, Any] = await _call(client, "get_window_state", {"window_id": window_id})
        if any(e["role"] == "push button" and e["name"] == "Count" for e in state["elements"]):
            return state
        await asyncio.sleep(0.1)
    pytest.fail(f"no complete tree for window {window_id}")


def _find(state: dict[str, Any], role: str, name: str | None = None) -> dict[str, Any]:
    return next(
        e for e in state["elements"] if e["role"] == role and (name is None or e["name"] == name)
    )


async def test_read_click_and_type(demo: str) -> None:
    async with _server() as client:
        window_id = await _window(client, demo)
        state = await _state(client, window_id)
        assert state["source"] == "atspi"
        assert state["coordinates"] == "window"

        button = _find(state, "push button", "Count")
        geometry = state["elements"][0]["geometry"]
        assert 0 <= button["geometry"]["x"] < geometry["width"]  # window-relative
        entry = next(e for e in state["elements"] if "editable" in e["state"])

        await _call(client, "click", {"window_id": window_id, "element": button["index"]})
        await _call(client, "type_text", {
            "window_id": window_id, "element": entry["index"], "text": "Ada",
        })
        await asyncio.sleep(0.3)
        after = await _state(client, window_id)
        assert _find(after, "label", "Clicks: 1")
        assert next(e for e in after["elements"] if "editable" in e["state"])["value"] == "Ada"


async def test_unsupported_actions_explain_why(demo: str) -> None:
    async with _server() as client:
        window_id = await _window(client, demo)
        state = await _state(client, window_id)
        label = _find(state, "label")
        refusals = [
            ("press_key", {"window_id": window_id, "keys": "Return"}),
            ("scroll", {"window_id": window_id, "direction": "down"}),
            ("click", {"window_id": window_id, "x": 5, "y": 5}),
            ("type_text", {"window_id": window_id, "text": "x"}),
            ("click", {"window_id": window_id, "element": label["index"]}),
            ("screenshot_window", {"window_id": window_id}),
            ("screenshot_desktop", {}),
        ]
        for tool, args in refusals:
            message = await _refused(client, tool, args)
            assert "Wayland" in message or "portal" in message, (tool, message)


@pytest.fixture(params=sorted(TOOLKITS))
def long_list(request: pytest.FixtureRequest) -> Iterator[str]:
    app, version = TOOLKITS[request.param]
    if not _gtk(version):
        pytest.skip(f"needs GTK {version}")
    title = f"LCU Wayland list {request.param}"
    proc = _launch(app, title, "--rows", "200")
    yield title
    proc.kill()
    proc.wait()


async def test_scroll_moves_the_list_without_a_pointer(long_list: str) -> None:
    async with _server() as client:
        window_id = await _window(client, long_list)
        state = await _state(client, window_id)
        rows = [e for e in state["elements"] if e["name"].startswith("Row ")]
        assert rows, "no rows visible"
        first = {e["name"] for e in rows}
        await _call(client, "scroll", {
            "window_id": window_id, "element": rows[0]["index"], "direction": "down", "amount": 5,
        })
        new: list[dict[str, Any]] = []
        for _ in range(20):
            await asyncio.sleep(0.1)
            later = await _state(client, window_id)
            new = [e for e in later["elements"]
                   if e["name"].startswith("Row ") and e["name"] not in first]
            if new:
                break
        assert new, "scrolling revealed no new rows"


async def test_password_window_is_read_only(login: str) -> None:
    async with _server() as client:
        window_id = await _window(client, login)
        state = await _state(client, window_id)
        assert state["sensitive"] is True
        password = _find(state, "password text")
        assert password["value"] is None
        message = await _refused(client, "type_text", {
            "window_id": window_id, "element": password["index"], "text": "hunter2",
        })
        assert "password field" in message
        button = _find(state, "push button", "Count")
        assert "password field" in await _refused(
            client, "click", {"window_id": window_id, "element": button["index"]}
        )
