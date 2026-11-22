# 02. Clicks by position on Wayland

**Status:** blocked on the pointer probe output (subgoal 01, step 2)
**Depends on:** 01
**Design:** `docs/design/wayland-phase2.md`, slice 2d

## Goal
`click(window_id, x, y)` and the pointer fallback for elements with no
accessible action work on Wayland, at AT-SPI's window-relative positions.

## Approach
A RemoteDesktop session combined with a ScreenCast stream of the **target window**
(`SelectSources` `types=2`). `NotifyPointerMotionAbsolute` coordinates are
relative to that stream, and so window-relative like AT-SPI's, so no window
screen origin is needed.

## Steps
1. Read the probe's `RESULT:` line.
   - **HIT with offset none/centred/top-left inset:** use that offset model.
   - **Window streams not offered or no hit:** fall back to KWin scripting on KDE.
     GNOME stays refused, so record why in the design doc.
2. Extend `Portal.remote_desktop()` to request `POINTER` and a window stream,
   keyed per window. Each window is a separate user pick; the restore token
   brings back the choice.
3. Verify the stream is the right window before every click: compare the stream
   size with AT-SPI's frame size within a tolerance. Refuse on mismatch.
4. Implement `WaylandDriver.click_coordinate` and the element-centre fallback in
   `click`. Use `NotifyPointerMotionAbsolute`, then `NotifyPointerButton` (BTN_LEFT 0x110).
5. Keep the guards: target window must be focused or frontmost, no password field, element not stale.
6. Extend the fake portal (`tests/integration/test_portal_dbus.py`) with ScreenCast and pointer methods. Add unit tests for offset maths and size mismatch.
7. Add a step to `tests/manual/portal.md`.

## Done when
- Clicking the GTK demo's button by position works on GNOME, run by hand.
- Size-mismatch and wrong-window cases refuse.
- Fake-portal tests cover the pointer path.
