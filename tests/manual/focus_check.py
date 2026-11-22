#!/usr/bin/env python3
"""Print which window AT-SPI thinks has keyboard focus, whenever it changes.

Read-only: sends no input and needs no permissions. Run it in a Wayland
session for 20 seconds while switching between 3 or 4 windows (click and
Alt+Tab), including a text editor and a terminal, and note which window you
were really in at each step.

The desktop passes if, at every step, exactly one window reports focus, it is
the window you were in, and the line updates within about a second. Only then
add the desktop to KEYBOARD_VERIFIED_DESKTOPS in drivers/wayland.py.
Chrome and Electron apps stay silent unless started with accessibility on.
"""
import time
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

ROLES = {"frame", "dialog", "window", "alert", "file chooser"}

def states(node):
    try:
        return {s.value_nick for s in node.get_state_set().get_states()}
    except Exception:
        return set()

def focused_in(node, depth=0):
    if depth > 40:
        return None
    if "focused" in states(node):
        return node
    try:
        for i in range(node.get_child_count()):
            hit = focused_in(node.get_child_at_index(i), depth + 1)
            if hit is not None:
                return hit
    except Exception:
        pass
    return None

def snapshot():
    desktop = Atspi.get_desktop(0)
    rows = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        for j in range(app.get_child_count()):
            win = app.get_child_at_index(j)
            if win.get_role_name() not in ROLES or "showing" not in states(win):
                continue
            hit = focused_in(win)
            active = "active" in states(win)
            if active or hit is not None:
                what = f"{hit.get_role_name()} {hit.get_name()!r}" if hit else "-"
                rows.append(f"{app.get_name()} / {win.get_name()!r}: active={active} focused={what}")
    return rows

print("Switch between windows (click or Alt+Tab) for 20 seconds...")
last = None
end = time.time() + 20
while time.time() < end:
    now = snapshot()
    if now != last:
        print(time.strftime("%H:%M:%S"), "->", now or ["(nothing reports focus)"])
        last = now
    time.sleep(0.5)
