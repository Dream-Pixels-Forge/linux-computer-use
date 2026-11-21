"""End-to-end test: the real MCP server, over stdio, against a real X display.

Skipped unless DISPLAY is set and xdotool, scrot and xterm are installed.
In CI it runs under Xvfb:  xvfb-run -a pytest tests/integration
"""

from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from PIL import Image

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY")
    or not all(shutil.which(tool) for tool in ("xdotool", "scrot", "xterm")),
    reason="needs an X display plus xdotool, scrot and xterm",
)

TITLE = "lcu-integration-target"


@pytest.fixture
def target_window(tmp_path: Path) -> Iterator[tuple[int, Path]]:
    """An xterm running `cat > out.txt`, so typed lines land in a file."""
    out = tmp_path / "out.txt"
    proc = subprocess.Popen(
        [
            "xterm", "-T", TITLE, "-geometry", "60x10+40+30",
            "-xrm", "XTerm*allowTitleOps: false",
            "-e", "sh", "-c", f"cat > {out}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    window_id = None
    for _ in range(50):
        found = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", TITLE],
            capture_output=True, text=True, check=False,
        ).stdout.split()
        if found:
            window_id = int(found[0])
            break
        time.sleep(0.1)
    if window_id is None:
        proc.kill()
        pytest.fail("xterm window did not appear")
    time.sleep(0.3)  # let it map and draw
    yield window_id, out
    proc.kill()
    proc.wait()


async def test_drive_a_real_window(target_window: tuple[int, Path]) -> None:
    window_id, out = target_window
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "linux_computer_use.mcp"], env=dict(os.environ)
    )
    async with Client(params) as client:
        listed = await client.call_tool("list_windows", {})
        assert not listed.is_error
        window = next(
            w for w in listed.structured_content["windows"] if w["window_id"] == window_id
        )
        assert window["title"] == TITLE
        assert window["pid"] > 0
        geometry = window["geometry"]
        assert geometry["width"] > 0 and geometry["height"] > 0

        typed = await client.call_tool(
            "type_text", {"text": "hello from mcp", "window_id": window_id}
        )
        assert not typed.is_error, typed.content
        pressed = await client.call_tool("press_key", {"keys": "Return", "window_id": window_id})
        assert not pressed.is_error, pressed.content

        for _ in range(30):
            if out.exists() and out.read_text():
                break
            time.sleep(0.1)
        assert out.read_text() == "hello from mcp\n"

        shot = await client.call_tool("screenshot_window", {"window_id": window_id})
        assert not shot.is_error
        image = Image.open(io.BytesIO(base64.b64decode(shot.content[0].data)))
        assert image.size == (geometry["width"], geometry["height"])

        missing = await client.call_tool("get_app_info", {"window_id": 1})
        assert missing.is_error
