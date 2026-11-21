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
