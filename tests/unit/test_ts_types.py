"""Keep src/types/index.ts in step with what the MCP server really sends.

Parses the TypeScript interfaces and compares them with the server's tool
input schemas and with real tool output (via the fake driver), so a field
added, renamed or made optional on one side fails here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from linux_computer_use.drivers.base import Element, Window
from linux_computer_use.mcp import server
from linux_computer_use.mcp.server import mcp
from mcp.client import Client

from tests.unit.test_mcp_server import ELEMENTS, WINDOW, FakeDriver

TYPES = Path(__file__).parents[2] / "src" / "types" / "index.ts"


def parse_interfaces(source: str) -> dict[str, dict[str, bool]]:
    """Map interface name -> {field: optional} for top-level fields."""
    interfaces: dict[str, dict[str, bool]] = {}
    for match in re.finditer(r"export interface (\w+) \{\n(.*?)\n\}", source, re.S):
        fields: dict[str, bool] = {}
        for line in match.group(2).splitlines():
            field = re.match(r"\s{2}(\w+)(\?)?:", line)
            if field:
                fields[field.group(1)] = field.group(2) == "?"
        interfaces[match.group(1)] = fields
    return interfaces


TS = parse_interfaces(TYPES.read_text())

ARGS = {
    "get_window_state": "GetWindowStateArgs",
    "get_app_info": "GetAppInfoArgs",
    "click": "ClickArgs",
    "type_text": "TypeTextArgs",
    "press_key": "PressKeyArgs",
    "scroll": "ScrollArgs",
    "screenshot_desktop": "ScreenshotDesktopArgs",
    "screenshot_window": "ScreenshotWindowArgs",
    "screenshot_element": "ScreenshotElementArgs",
}
NO_ARGS = {"list_apps", "list_windows"}

# tool -> (result interface, arguments that produce a successful call)
RESULTS: dict[str, tuple[str, dict[str, Any]]] = {
    "list_apps": ("ListAppsResult", {}),
    "list_windows": ("ListWindowsResult", {}),
    "get_window_state": ("WindowStateResult", {"window_id": 42}),
    "get_app_info": ("AppInfoResult", {"window_id": 42}),
    "click": ("ClickResult", {"window_id": 42, "element": 1}),
    "type_text": ("TypeTextResult", {"text": "hi", "window_id": 42}),
    "press_key": ("PressKeyResult", {"keys": "Return", "window_id": 42}),
    "scroll": ("ScrollResult", {"direction": "down", "window_id": 42}),
}
SCREENSHOTS: dict[str, tuple[str, dict[str, Any]]] = {
    "screenshot_desktop": ("ScreenshotDesktopMeta", {}),
    "screenshot_window": ("ScreenshotWindowMeta", {"window_id": 42}),
    "screenshot_element": ("ScreenshotElementMeta", {"window_id": 42, "element": 1}),
}


def required(name: str) -> set[str]:
    return {f for f, optional in TS[name].items() if not optional}


@pytest.fixture
def driver(tmp_path: Path):
    from PIL import Image as PILImage

    shot = tmp_path / "screen.png"
    PILImage.new("RGB", (1920, 1080)).save(shot)
    fake = FakeDriver(shot)
    server.set_driver(fake)
    server._snapshots.clear()
    yield fake
    server.set_driver(None)
    server._snapshots.clear()


async def tools() -> dict[str, Any]:
    async with Client(mcp) as client:
        return {t.name: t for t in (await client.list_tools()).tools}


def test_parser_sees_the_interfaces():
    assert {"Element", "Window", "ClickArgs", "WindowStateResult", "ToolArgs"} <= TS.keys()
    assert TS["ClickArgs"] == {"window_id": False, "element": True, "x": True, "y": True}


async def test_tool_maps_cover_every_tool():
    names = set(await tools())
    assert set(TS["ToolArgs"]) == names
    assert set(TS["ToolResults"]) == names
    assert set(ARGS) | NO_ARGS == names


@pytest.mark.parametrize("tool", sorted(ARGS))
async def test_args_match_input_schema(tool: str):
    schema = (await tools())[tool].input_schema
    interface = ARGS[tool]
    assert set(TS[interface]) == set(schema.get("properties", {})), interface
    assert required(interface) == set(schema.get("required", [])), interface


@pytest.mark.parametrize("tool", sorted(NO_ARGS))
async def test_no_arg_tools_take_no_args(tool: str):
    assert not (await tools())[tool].input_schema.get("properties")


@pytest.mark.parametrize("tool", sorted(RESULTS))
async def test_results_match_structured_output(driver, tool: str):
    interface, args = RESULTS[tool]
    async with Client(mcp) as client:
        if tool == "click":
            await client.call_tool("get_window_state", {"window_id": 42})
        result = await client.call_tool(tool, args)
    assert not result.is_error, result.content
    assert set(result.structured_content) == set(TS[interface]), interface
    assert required(interface) == set(TS[interface]), f"{interface} fields are always sent"


@pytest.mark.parametrize("tool", sorted(SCREENSHOTS))
async def test_screenshot_meta_matches(driver, tool: str):
    interface, args = SCREENSHOTS[tool]
    async with Client(mcp) as client:
        if tool == "screenshot_element":
            await client.call_tool("get_window_state", {"window_id": 42})
        result = await client.call_tool(tool, args)
    assert not result.is_error, result.content
    image, meta = result.content
    assert image.type == "image"
    assert set(json.loads(meta.text)) == set(TS[interface]), interface


def test_element_and_window_shapes():
    element = Element(**vars(ELEMENTS[1])).to_dict()
    assert set(element) == set(TS["Element"]) == required("Element")
    assert set(element["geometry"]) == set(TS["Geometry"])
    window = Window(**vars(WINDOW)).to_dict()
    assert set(window) == set(TS["Window"]) == required("Window")


def test_app_shape(tmp_path: Path):
    (tmp_path / "a.desktop").write_text("[Desktop Entry]\nType=Application\nName=A\n")
    (app,) = server.discover_apps([tmp_path])
    assert set(app) == set(TS["App"]) == required("App")


async def test_app_info_window_refs(driver):
    async with Client(mcp) as client:
        result = await client.call_tool("get_app_info", {"window_id": 42})
    (ref,) = result.structured_content["windows"]
    assert set(ref) == set(TS["WindowRef"])
