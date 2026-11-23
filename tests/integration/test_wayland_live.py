"""End-to-end test: the Wayland driver, through the real MCP server.

Needs a Wayland compositor (WAYLAND_DISPLAY), a D-Bus session with the AT-SPI
bus, and a Python with the demo apps' toolkit. In CI, inside dbus-run-session:

    weston --backend=headless --socket=wayland-1 &
    WAYLAND_DISPLAY=wayland-1 pytest tests/integration/test_wayland_live.py

Toolkits (each skips when its runtime is missing):

    gtk3, gtk4   GTK 3/4 demo apps launched with LCU_GTK_PYTHON (default /usr/bin/python3)
    qt6          PySide6 demo app, runs when PySide6 is importable
    firefox      demo.html via Firefox (needs MOZ_ENABLE_WAYLAND=1 + fresh profile)
    chromium     demo.html via Chromium with --force-renderer-accessibility
    libreoffice  soffice (AT-SPI exposure under headless Weston unverified)

Non-GTK toolkits (qt6, firefox, chromium, libreoffice) only run when
explicitly opted in via LCU_WAYLAND_LIVE_TOOLKITS, since they need
compositor-specific setup that isn't safe to assume everywhere:

    LCU_WAYLAND_LIVE_TOOLKITS=qt6 pytest tests/integration/test_wayland_live.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
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


def _qt6() -> bool:
    return subprocess.run(
        [sys.executable, "-c", "import PySide6"], capture_output=True, check=False
    ).returncode == 0


def _binary(name: str) -> str | None:
    return shutil.which(name)


_NON_GTK = {"qt6", "firefox", "chromium", "libreoffice"}


def _toolkit_enabled(name: str) -> bool:
    if name not in _NON_GTK:
        return True
    enabled = [t.strip() for t in os.environ.get("LCU_WAYLAND_LIVE_TOOLKITS", "").split(",") if t.strip()]
    return name in enabled


# (check, command factory) per toolkit. The factory receives the demo title
# and any extra args, and returns the subprocess command list.
TOOLKITS: dict[str, tuple[Any, Any]] = {
    "gtk3": (
        lambda: _gtk("3.0") and _toolkit_enabled("gtk3"),
        lambda title, *extra: [GTK_PYTHON, str(APPS / "gtk_demo.py"), title, *extra],
    ),
    "gtk4": (
        lambda: _gtk("4.0") and _toolkit_enabled("gtk4"),
        lambda title, *extra: [GTK_PYTHON, str(APPS / "gtk4_demo.py"), title, *extra],
    ),
    "qt6": (
        lambda: _qt6() and _toolkit_enabled("qt6"),
        lambda title, *extra: [sys.executable, str(APPS / "qt6_demo.py"), title, *extra],
    ),
    "firefox": (
        lambda: _binary("firefox") and _toolkit_enabled("firefox"),
        lambda title, *extra: [
            "firefox",
            "--new-window",
            (APPS / "demo.html").as_uri() + "?title=" + title,
        ],
    ),
    "chromium": (
        lambda: _binary("chromium-browser") or _binary("chromium"),
        lambda title, *extra: [
            _binary("chromium-browser") or "chromium",
            "--force-renderer-accessibility",
            "--new-window",
            (APPS / "demo.html").as_uri() + "?title=" + title,
        ],
    ),
    "libreoffice": (
        lambda: _binary("soffice") and _toolkit_enabled("libreoffice"),
        lambda title, *extra: ["soffice", "--writer", str(APPS / "demo.html")],
    ),
}

_MODULE_SKIP = (
    not os.environ.get("WAYLAND_DISPLAY")
    or not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    or not ATSPIDriver().available
)

pytestmark = pytest.mark.skipif(
    _MODULE_SKIP,
    reason="needs a Wayland compositor, a D-Bus session and PyGObject/AT-SPI",
)


def _env() -> dict[str, str]:
    env = dict(os.environ, GDK_BACKEND="wayland")
    env.pop("DISPLAY", None)  # make sure nothing silently falls back to X11
    return env


def _launch(cmd: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(cmd, env=_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,)


def _demos_enabled() -> list[str]:
    return sorted(name for name, (check, _) in TOOLKITS.items() if check())


@pytest.fixture(params=_demos_enabled())
def demo(request: pytest.FixtureRequest) -> Iterator[str]:
    name = request.param
    check, factory = TOOLKITS[name]
    if not check():
        pytest.skip(f"{name} runtime not available")
    title = f"LCU Wayland {name}"
    proc = _launch(factory(title))
    yield title
    proc.kill()
    proc.wait()


@pytest.fixture
def login() -> Iterator[str]:
    name = "gtk3"
    check, factory = TOOLKITS[name]
    if not check():
        pytest.skip(f"{name} runtime not available")
    title = "LCU Wayland Login"
    proc = _launch(factory(title, "--password"))
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


@pytest.fixture(params=_demos_enabled())
def long_list(request: pytest.FixtureRequest) -> Iterator[str]:
    name = request.param
    check, factory = TOOLKITS[name]
    if not check():
        pytest.skip(f"{name} runtime not available")
    title = f"LCU Wayland list {name}"
    proc = _launch(factory(title, "--rows", "200"))
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
