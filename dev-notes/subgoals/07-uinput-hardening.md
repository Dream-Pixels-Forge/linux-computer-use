# 07. uinput keyboard: real-device test and more layouts

**Status:** not started
**Depends on:** 01

## Goal
The phase 3 keyboard is proven on a real `/dev/uinput`, and supports more than the US layout.

## Steps
1. On a VM or kiosk image: `modprobe uinput`, set up the udev rule, and run the
   uinput section of `tests/manual/portal.md`. Confirm the 0.2 s device-appearance
   delay is enough, or tune it.
2. Consider a CI job on a runner where `/dev/uinput` is available (many GitHub
   runners allow `sudo modprobe uinput`). Type into the GTK demo under Weston and
   read the value back over AT-SPI.
3. Layouts: build keysym-to-keycode tables from xkbcommon (`python-xkbcommon` or
   `ctypes` on libxkbcommon) instead of the hand-written US table, so
   `LCU_WAYLAND_UINPUT=de` and others work.
4. Decide whether to add a uinput pointer. It needs absolute positioning and
   screen geometry, the same problem as subgoal 02. Probably not worth it.

## Done when
A real-device run is recorded, and at least one extra layout is supported or a decision is recorded against it.
