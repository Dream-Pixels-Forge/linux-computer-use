#!/usr/bin/env python3
"""Probe: can the portal click inside one window using AT-SPI's positions?

Answers the open questions before clicks by position are built (see
docs/design/wayland-phase2.md, slice 2d):

1. Does a RemoteDesktop session accept absolute pointer motion on a
   ScreenCast stream of a single *window* (not a monitor)?
2. Do that stream's coordinates line up with AT-SPI's window-relative
   positions, or is there an offset (client-side decorations, shadows)?

It opens the GTK demo app, asks the portal for pointer access plus a stream
of one window (pick the "LCU Pointer Probe" window in the dialog), then
moves the pointer to the centre of the demo's "Count" button, as AT-SPI
reports it, and clicks. The demo's label shows whether the click landed. If
it missed, it tries the offsets the sizes suggest and reports which works.

Run in a GNOME or KDE Wayland session, from the repository root:

    python3 tests/manual/pointer_probe.py

Needs PyGObject with Atspi, GTK 3 (python3-gi, gir1.2-gtk-3.0,
gir1.2-atspi-2.0) and xdg-desktop-portal. It clicks only inside the demo
window it starts. Paste the full output into the PR.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from linux_computer_use.drivers import portal  # noqa: E402
from linux_computer_use.drivers.atspi import ATSPIDriver  # noqa: E402

TITLE = "LCU Pointer Probe"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
WINDOW_SOURCE = 2
BTN_LEFT = 0x110


def find_window(atspi: ATSPIDriver) -> tuple[Any, Any]:
    for _ in range(100):
        for app, frame in atspi.list_frames():
            if frame.get_name() == TITLE:
                return app, frame
        time.sleep(0.1)
    sys.exit("The demo window never appeared on the accessibility bus.")


def read(atspi: ATSPIDriver, frame: Any) -> tuple[Any, str, tuple[int, int, int, int]]:
    tree = atspi.read_tree(frame, 1, None, (0, 0))
    button = next(e for e in tree.elements if e.role == "push button" and e.name == "Count")
    label = next(e for e in tree.elements if e.role == "label" and e.name.startswith("Clicks"))
    root = tree.elements[0]
    return button, label.name, (root.x, root.y, root.width, root.height)


def main() -> None:
    atspi = ATSPIDriver()
    if not atspi.connect():
        sys.exit("AT-SPI is not available (install gir1.2-atspi-2.0 and PyGObject).")
    demo = ROOT / "tests" / "integration" / "apps" / "gtk_demo.py"
    proc = subprocess.Popen(
        [os.environ.get("LCU_GTK_PYTHON", "/usr/bin/python3"), str(demo), TITLE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        run(atspi)
    except portal.PortalError as exc:
        print(f"RESULT: the portal refused or isn't available: {exc}")
    finally:
        proc.kill()


def run(atspi: ATSPIDriver) -> None:
    _app, frame = find_window(atspi)
    time.sleep(0.5)
    button, label, frame_rect = read(atspi, frame)
    print(f"desktop: {os.environ.get('XDG_CURRENT_DESKTOP')!r}")
    print(f"AT-SPI frame (window-relative): {frame_rect}")
    print(f"AT-SPI Count button: x={button.x} y={button.y} w={button.width} h={button.height}")
    print(f"label before: {label!r}")

    p = portal.Portal()  # no restore token: the probe always asks
    v = p._variant()
    token = "lcu_probe" + os.urandom(4).hex()
    created = p.request(
        portal.REMOTE_DESKTOP_IFACE, "CreateSession",
        lambda t: v("(a{sv})", ({"handle_token": v("s", t),
                                 "session_handle_token": v("s", token)},)),
    )
    handle = str(created["session_handle"])
    p.request(
        portal.REMOTE_DESKTOP_IFACE, "SelectDevices",
        lambda t: v("(oa{sv})", (handle, {"handle_token": v("s", t),
                                          "types": v("u", portal.POINTER)})),
    )
    try:
        p.request(
            SCREENCAST_IFACE, "SelectSources",
            lambda t: v("(oa{sv})", (handle, {"handle_token": v("s", t),
                                              "types": v("u", WINDOW_SOURCE),
                                              "multiple": v("b", False)})),  # noqa: FBT003
        )
    except portal.PortalError as exc:
        print(f"RESULT: window streams not offered in a RemoteDesktop session: {exc}")
        return
    print(f"Pick the {TITLE!r} window in the dialog...")
    started = p.request(
        portal.REMOTE_DESKTOP_IFACE, "Start",
        lambda t: v("(osa{sv})", (handle, "", {"handle_token": v("s", t)})),
        timeout=portal.DIALOG_TIMEOUT,
    )
    streams = started.get("streams") or []
    print(f"granted devices: {started.get('devices')}  streams: {streams}")
    if not streams:
        print("RESULT: no stream returned; absolute pointer motion is impossible.")
        return
    node, props = streams[0]
    size = props.get("size")
    print(f"stream node {node}: source_type={props.get('source_type')} size={size}")

    def click(x: float, y: float) -> str:
        p.call(portal.REMOTE_DESKTOP_IFACE, "NotifyPointerMotionAbsolute",
               v("(oa{sv}udd)", (handle, {}, node, float(x), float(y))))
        time.sleep(0.1)
        for state in (1, 0):
            p.call(portal.REMOTE_DESKTOP_IFACE, "NotifyPointerButton",
                   v("(oa{sv}iu)", (handle, {}, BTN_LEFT, state)))
            time.sleep(0.05)
        time.sleep(0.5)
        return read(atspi, frame)[1]

    cx, cy = button.x + button.width / 2, button.y + button.height / 2
    candidates = [("none", 0.0, 0.0)]
    if size:
        dw, dh = size[0] - frame_rect[2], size[1] - frame_rect[3]
        candidates += [("centred", dw / 2, dh / 2), ("top-left inset", dw, dh)]
    last = label
    try:
        for name, ox, oy in candidates:
            now = click(cx + ox, cy + oy)
            hit = now != last
            print(f"offset {name} ({ox:+.0f}, {oy:+.0f}): label {now!r} -> {'HIT' if hit else 'miss'}")
            if hit:
                print(f"RESULT: window-stream clicks work with offset {name!r}.")
                return
            last = now
        print("RESULT: no candidate offset hit the button; paste this output into the PR.")
    finally:
        with contextlib.suppress(portal.PortalError):
            p.call(portal.SESSION_IFACE, "Close", None, path=handle)


if __name__ == "__main__":
    main()
