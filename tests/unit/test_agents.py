"""Unit tests for agent integration helpers."""

import json
from pathlib import Path

from linux_computer_use.agents.opencode import OpencodeIntegration


async def test_configure_mcp_merges_existing_config(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("linux_computer_use.agents.base.MCPToolProxy.__init__", lambda self: None)
    config = tmp_path / "opencode" / "mcp.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"theme": "dark", "servers": {"other": {"command": "x"}}}))

    assert await OpencodeIntegration().configure_mcp(str(config))

    data = json.loads(config.read_text())
    assert data["theme"] == "dark"
    assert data["servers"]["other"] == {"command": "x"}
    assert data["servers"]["linux-computer-use"]["args"] == ["-m", "linux_computer_use.mcp"]


async def test_configure_mcp_creates_missing_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("linux_computer_use.agents.base.MCPToolProxy.__init__", lambda self: None)
    config = tmp_path / "new" / "mcp.json"

    assert await OpencodeIntegration().configure_mcp(str(config))
    assert "linux-computer-use" in json.loads(config.read_text())["servers"]


async def test_tool_proxy_uses_real_server_tools(tmp_path: Path):
    """The proxy goes through the MCP tools, so their safety checks apply."""
    from linux_computer_use.agents.base import MCPToolProxy
    from linux_computer_use.mcp import server
    from PIL import Image as PILImage

    from tests.unit.test_mcp_server import FakeDriver

    shot = tmp_path / "s.png"
    PILImage.new("RGB", (1920, 1080)).save(shot)
    fake = FakeDriver(shot)
    server.set_driver(fake)
    server._snapshots.clear()
    try:
        proxy = MCPToolProxy()
        assert (await proxy.list_windows())["count"] == 1
        assert "first" in (await proxy.click(element=1, window_id=42))["error"]
        await proxy.get_window_state(42)
        assert (await proxy.click(element=1, window_id=42))["effect"] == "confirmed"
        assert (await proxy.click(coordinate={"x": 105, "y": 56}, window_id=42))["effect"] == "confirmed"
        assert fake.calls == [("click", 1), ("click_coordinate", 105, 56)]

        fake.sensitive = True
        assert "password field" in (await proxy.type_text("x", window_id=42))["error"]

        shot_result = await proxy.screenshot_window(42)
        assert shot_result["base64"] and shot_result["path"].endswith(".png")
    finally:
        server.set_driver(None)
        server._snapshots.clear()
