"""Unit tests for the MCP server, using a fake desktop driver."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from linux_computer_use.drivers.base import Element, Window, WindowState
from linux_computer_use.mcp import server
from linux_computer_use.mcp.server import discover_apps, mcp, set_driver
from mcp.client import Client
from PIL import Image as PILImage

WINDOW = Window(
    window_id=42, pid=1000, app_id="gedit", title="Notes", x=100, y=50,
    width=400, height=300, workspace=0, visible=True, app="Text Editor",
)
ELEMENTS = [
    Element(index=0, role="window", name="Notes", x=100, y=50, width=400, height=300, window_id=42),
    Element(index=1, role="button", name="Save", x=110, y=60, width=40, height=20, window_id=42),
]


class FakeDriver:
    def __init__(self, screenshot: Path) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.screenshot = screenshot

    def connect(self) -> bool:
        return True

    def list_windows(self) -> list[Window]:
        return [WINDOW]

    def get_window_state(self, window_id: int) -> WindowState:
        return WindowState(window_id, 1000, "", "- [window] Notes", list(ELEMENTS))

    def click(self, element: Element) -> bool:
        self.calls.append(("click", element.index))
        return True

    def click_coordinate(self, x: int, y: int) -> bool:
        self.calls.append(("click_coordinate", x, y))
        return True

    def type_text(self, text: str, element: Element) -> bool:
        self.calls.append(("type_text", text, element.index))
        return True

    def press_key(self, keys: str, element: Element | None = None) -> bool:
        self.calls.append(("press_key", keys))
        return True

    def scroll(self, direction: str, amount: int, element: Element) -> bool:
        self.calls.append(("scroll", direction, amount, element.index))
        return True

    def focus_window(self, window_id: int) -> bool:
        self.calls.append(("focus", window_id))
        return True

    def screenshot_desktop(self, region: tuple[int, int, int, int] | None = None) -> str:
        return str(self.screenshot)


@pytest.fixture
def driver(tmp_path: Path):
    shot = tmp_path / "screen.png"
    PILImage.new("RGB", (1920, 1080), "white").save(shot)
    fake = FakeDriver(shot)
    set_driver(fake)
    yield fake
    set_driver(None)


async def call(name: str, args: dict[str, Any] | None = None):
    """Call a tool through a real in-memory MCP client session."""
    async with Client(mcp) as client:
        return await client.call_tool(name, args or {})


def structured(result) -> dict[str, Any]:
    assert not result.is_error, result.content
    return result.structured_content


def error_text(result) -> str:
    assert result.is_error
    return result.content[0].text


async def list_tools():
    async with Client(mcp) as client:
        return (await client.list_tools()).tools


async def test_registers_expected_tools():
    names = {t.name for t in await list_tools()}
    assert names == {
        "list_apps", "list_windows", "get_window_state", "get_app_info", "click",
        "type_text", "press_key", "scroll", "screenshot_desktop",
        "screenshot_window", "screenshot_element",
    }


async def test_schemas_mark_required_args():
    tools = {t.name: t for t in await list_tools()}
    assert tools["get_window_state"].input_schema["required"] == ["window_id"]
    assert tools["list_windows"].input_schema.get("required", []) == []
    scroll_dir = tools["scroll"].input_schema["properties"]["direction"]
    assert set(scroll_dir["enum"]) == {"up", "down", "left", "right"}


async def test_list_windows(driver):
    data = structured(await call("list_windows"))
    assert data["count"] == 1
    assert data["windows"][0]["window_id"] == 42


async def test_get_window_state(driver):
    data = structured(await call("get_window_state", {"window_id": 42}))
    assert [e["name"] for e in data["elements"]] == ["Notes", "Save"]


async def test_get_app_info(driver):
    data = structured(await call("get_app_info", {"window_id": 42}))
    assert data["name"] == "Text Editor"
    assert data["pid"] == 1000


async def test_click_element(driver):
    data = structured(await call("click", {"window_id": 42, "element": 1}))
    assert data["effect"] == "confirmed"
    assert driver.calls == [("click", 1)]


async def test_click_coordinate(driver):
    structured(await call("click", {"window_id": 42, "x": 5, "y": 6}))
    assert driver.calls == [("click_coordinate", 5, 6)]


async def test_click_requires_target(driver):
    assert "element index" in error_text(await call("click", {"window_id": 42}))
    assert driver.calls == []


async def test_click_unknown_element(driver):
    assert "Element 9 not found" in error_text(await call("click", {"window_id": 42, "element": 9}))


async def test_unknown_window(driver):
    result = await call("press_key", {"keys": "a", "window_id": 7})
    assert "Window 7 not found" in error_text(result)


async def test_type_text_without_element_focuses_window(driver):
    data = structured(await call("type_text", {"text": "hi", "window_id": 42}))
    assert data["characters_typed"] == 2
    assert driver.calls == [("focus", 42), ("type_text", "hi", 0)]


async def test_press_key(driver):
    structured(await call("press_key", {"keys": "ctrl+s", "window_id": 42}))
    assert driver.calls == [("focus", 42), ("press_key", "ctrl+s")]


async def test_scroll(driver):
    structured(await call("scroll", {"direction": "down", "window_id": 42, "amount": 5}))
    assert driver.calls == [("scroll", "down", 5, 0)]


async def test_scroll_rejects_bad_amount(driver):
    assert "between 1 and 100" in error_text(
        await call("scroll", {"direction": "down", "window_id": 42, "amount": 0})
    )


async def test_scroll_rejects_bad_direction(driver):
    result = await call("scroll", {"direction": "sideways", "window_id": 42})
    assert result.is_error


async def test_screenshot_window_is_cropped(driver):
    result = await call("screenshot_window", {"window_id": 42})
    assert not result.is_error
    image, meta = result.content
    assert image.type == "image" and image.mime_type == "image/png"
    path = json.loads(meta.text)["path"]
    with PILImage.open(path) as img:
        assert img.size == (400, 300)


async def test_screenshot_element_is_cropped(driver):
    result = await call("screenshot_element", {"window_id": 42, "element": 1})
    path = json.loads(result.content[1].text)["path"]
    with PILImage.open(path) as img:
        assert img.size == (40, 20)


async def test_screenshot_desktop_partial_region_rejected(driver):
    assert "all of x, y, width and height" in error_text(
        await call("screenshot_desktop", {"x": 1})
    )


async def test_actions_are_audited(driver):
    session = server.get_active_session()
    before = len(session.actions_logged)
    await call("type_text", {"text": "my password is hunter2", "window_id": 42})
    entry = session.actions_logged[-1]
    assert len(session.actions_logged) == before + 1
    assert entry["tool"] == "type_text"
    assert entry["args"]["text"] == "***REDACTED***"


def test_discover_apps(tmp_path: Path):
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir()
    (apps_dir / "calc.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Calculator\nExec=gnome-calculator\n"
        "Categories=Utility;Science;\n"
    )
    (apps_dir / "hidden.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Hidden\nNoDisplay=true\n"
    )
    (apps_dir / "link.desktop").write_text("[Desktop Entry]\nType=Link\nName=Web\n")
    (apps_dir / "broken.desktop").write_text("not an ini file")

    apps = discover_apps([apps_dir])
    assert apps == [{
        "id": "calc", "name": "Calculator", "exec": "gnome-calculator",
        "categories": ["Utility", "Science"],
    }]


def test_missing_display_gives_clear_error(monkeypatch):
    from linux_computer_use.drivers import x11

    monkeypatch.setattr(x11.X11Driver, "connect", lambda self: False)
    set_driver(None)
    with pytest.raises(server.ToolError, match="X11 display"):
        server.get_driver()
