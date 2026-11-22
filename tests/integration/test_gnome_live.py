"""The portal paths on a real GNOME Shell, with nobody at the keyboard.

Runs only through ``tests/integration/run_gnome.sh``, which starts headless
GNOME Shell and xdg-desktop-portal with its GNOME backend. Portal dialogs are
approved over AT-SPI by ``apps/approve_portal.py``, and windows are focused
with ``org.gnome.Shell.Eval`` (the shell runs in unsafe mode for that).

What this proves that the fake portal can't: GNOME's real dialogs and
answers, the restore token skipping the dialog, the AT-SPI focus gate
matching what GNOME focuses, and keys reaching the right GTK 4 window.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from linux_computer_use.drivers import portal
from linux_computer_use.drivers.base import NotSupportedError
from linux_computer_use.drivers.wayland import WaylandDriver

pytestmark = pytest.mark.skipif(
    os.environ.get("LCU_GNOME_LIVE") != "1",
    reason="needs headless GNOME Shell; run tests/integration/run_gnome.sh",
)

APPS = Path(__file__).parent / "apps"
GTK_PYTHON = os.environ.get("LCU_GTK_PYTHON", "/usr/bin/python3")
SCREEN = (1280, 720)


def shell_eval(js: str) -> Any:
    out = subprocess.run(
        ["gdbus", "call", "--session", "-d", "org.gnome.Shell", "-o", "/org/gnome/Shell",
         "-m", "org.gnome.Shell.Eval", js],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out.startswith("(true,"), out
    return out


def approver(*buttons: str, timeout: float = 30) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [GTK_PYTHON, str(APPS / "approve_portal.py"), *buttons, "--timeout", str(timeout)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def wait_until(check: Callable[[], Any], what: str, timeout: float = 10) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.fixture(scope="module")
def tokens(tmp_path_factory: pytest.TempPathFactory) -> portal.TokenStore:
    return portal.TokenStore(tmp_path_factory.mktemp("state") / "token", keyring=None)


@pytest.fixture(scope="module")
def approved(tokens: portal.TokenStore, tmp_path_factory: pytest.TempPathFactory) -> None:
    """The first RemoteDesktop session: GNOME asks, the approver clicks Share."""
    clicker = approver("Share")
    first = portal.Portal(tokens=tokens, temp_dir=lambda: tmp_path_factory.mktemp("shots"))
    try:
        session = first.remote_desktop()
    except portal.PortalError as exc:
        clicker.kill()
        pytest.fail(f"{exc}\napprover said: {clicker.communicate()[0]}")
    finally:
        first.close()
    out, _ = clicker.communicate(timeout=40)
    assert clicker.returncode == 0, out
    assert session.devices & portal.KEYBOARD
    assert tokens.load(), "GNOME returned no restore token"


def test_restore_token_skips_the_dialog(approved: None, tokens: portal.TokenStore,
                                        tmp_path: Path) -> None:
    clicker = approver("Share", timeout=8)
    again = portal.Portal(tokens=tokens, temp_dir=lambda: tmp_path)
    started = time.monotonic()
    try:
        again.remote_desktop()
    finally:
        again.close()
    assert time.monotonic() - started < 5
    out, _ = clicker.communicate(timeout=20)
    assert clicker.returncode == 1, f"a dialog appeared although a token was stored: {out}"


@pytest.fixture
def windows() -> Iterator[Callable[[str], None]]:
    procs: list[subprocess.Popen[bytes]] = []

    def launch(title: str) -> None:
        env = dict(os.environ, GDK_BACKEND="wayland")
        procs.append(subprocess.Popen([GTK_PYTHON, str(APPS / "gtk4_demo.py"), title], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    yield launch
    for proc in procs:
        proc.kill()
        proc.wait()


def focus(title: str) -> None:
    shell_eval(
        "Main.overview.hide();"
        "const w = global.get_window_actors().map(a => a.meta_window)"
        f".find(w => w.get_title() == {json.dumps(title)});"
        "w.activate(global.get_current_time()); 'ok'"
    )


def test_keys_go_only_to_the_focused_window(
    approved: None, tokens: portal.TokenStore, tmp_path: Path, windows: Callable[[str], None]
) -> None:
    windows("LCU Alpha")
    windows("LCU Beta")
    driver = WaylandDriver(portal_client=portal.Portal(tokens=tokens, temp_dir=lambda: tmp_path))
    assert driver.connect()

    def ids() -> dict[str, int]:
        return {w.title: w.window_id for w in driver.list_windows()}

    found = wait_until(lambda: (lambda i: i if {"LCU Alpha", "LCU Beta"} <= set(i) else None)(ids()),
                       "both demo windows")
    alpha, beta = found["LCU Alpha"], found["LCU Beta"]

    # Headless mutter has no keyboard until a RemoteDesktop session sends a
    # first key; a real desktop always has one. Wake it with a Shift tap.
    assert driver.portal is not None
    session = driver.portal.remote_desktop()
    session.key(0xFFE1, pressed=True)
    session.key(0xFFE1, pressed=False)

    focus("LCU Alpha")
    wait_until(lambda: driver.focus_window(alpha) if _focused(driver, alpha) else None,
               "GNOME to focus Alpha")
    assert driver.type_text("hello gnome", driver.get_window_state(alpha).elements[0])
    wait_until(lambda: _entry(driver, alpha) == "hello gnome", "the text in Alpha")

    with pytest.raises(NotSupportedError, match="doesn't have keyboard focus"):
        driver.press_key("x", driver.get_window_state(beta).elements[0])
    assert _entry(driver, beta) == ""

    focus("LCU Beta")
    wait_until(lambda: _focused(driver, beta), "GNOME to focus Beta")
    assert driver.press_key("y", driver.get_window_state(beta).elements[0])
    wait_until(lambda: _entry(driver, beta) == "y", "the key in Beta")
    assert _entry(driver, alpha) == "hello gnome"
    driver.portal.close()


def _focused(driver: WaylandDriver, window_id: int) -> bool:
    try:
        return driver.focus_window(window_id)
    except NotSupportedError:
        return False


def _entry(driver: WaylandDriver, window_id: int) -> str | None:
    state = driver.get_window_state(window_id)
    entry = next(e for e in state.elements if e.role == "text")
    return entry.value


def test_screenshot_through_the_gnome_portal(tokens: portal.TokenStore, tmp_path: Path) -> None:
    # GNOME asks before a non-interactive screenshot unless the permission
    # store says yes; grant it the way "Allow" would.
    subprocess.run(
        ["gdbus", "call", "--session", "-d", "org.freedesktop.impl.portal.PermissionStore",
         "-o", "/org/freedesktop/impl/portal/PermissionStore",
         "-m", "org.freedesktop.impl.portal.PermissionStore.SetPermission",
         "screenshot", "true", "screenshot", "", "['yes']"],
        check=True, capture_output=True,
    )
    pictures = Path.home() / "Pictures"
    before = set(pictures.rglob("*")) if pictures.exists() else set()
    driver = WaylandDriver(portal_client=portal.Portal(tokens=tokens, temp_dir=lambda: tmp_path))
    path = Path(driver.screenshot_desktop())
    assert path.parent == tmp_path
    from PIL import Image

    with Image.open(path) as image:
        assert image.size == SCREEN
    after = set(pictures.rglob("*")) if pictures.exists() else set()
    assert after == before, "the portal's copy was left behind"
