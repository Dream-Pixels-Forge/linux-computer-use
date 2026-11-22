"""Approve a desktop portal dialog over AT-SPI, as a person would.

Used by the GNOME live tests, where nobody can click. Waits for a window of
xdg-desktop-portal-gnome, ticks its unticked options (such as "Allow Remote
Interaction", which the Share button needs), and presses the first button
whose label is given. Exits 0 once pressed, 1 if no dialog appeared in time.

    python3 approve_portal.py Share Allow [--timeout 30]
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterator
from typing import Any

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

PORTAL_APP = "xdg-desktop-portal-gnome"


def nodes(node: Any) -> Iterator[Any]:
    yield node
    for i in range(node.get_child_count()):
        child = node.get_child_at_index(i)
        if child is not None:
            yield from nodes(child)


def label(node: Any) -> str:
    return (node.get_name() or "").replace("_", "")


def portal_windows() -> list[Any]:
    desktop = Atspi.get_desktop(0)
    windows = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app is not None and app.get_name() == PORTAL_APP:
            windows += [app.get_child_at_index(j) for j in range(app.get_child_count())]
    return [w for w in windows if w is not None]


def press(window: Any, buttons: list[str]) -> str | None:
    for node in nodes(window):
        if (node.get_role() == Atspi.Role.CHECK_BOX
                and not label(node).startswith("Remember")
                and not node.get_state_set().contains(Atspi.StateType.CHECKED)):
            node.get_action_iface().do_action(0)
            time.sleep(0.5)
    for node in nodes(window):
        if (node.get_role() == Atspi.Role.PUSH_BUTTON
                and label(node) in buttons
                and node.get_state_set().contains(Atspi.StateType.SENSITIVE)):
            node.get_action_iface().do_action(0)
            return label(node)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("buttons", nargs="+")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        for window in portal_windows():
            pressed = press(window, args.buttons)
            if pressed:
                print(f"pressed {pressed} in {window.get_name()!r}", flush=True)
                return 0
        time.sleep(0.3)
    print("no portal dialog appeared", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
