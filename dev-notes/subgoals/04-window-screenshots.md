# 04. Window and element screenshots on Wayland

**Status:** not started
**Depends on:** 02 (shares the window ScreenCast stream)

## Goal
`screenshot_window` and `screenshot_element` work on Wayland. Today they are
refused, because the window's screen position is unknown.

## Approach
Capture one frame from the window's ScreenCast stream through PipeWire, then crop
the element at AT-SPI's window-relative position, using the offset found in subgoal 02.

## Steps
1. Choose a frame grabber. Options: GStreamer `pipewiresrc` via PyGObject (no new
   Python dependency, needs `gstreamer1.0-pipewire`), or a `pw-cat`/`gst-launch`
   subprocess. Use the `OpenPipeWireRemote` fd from the ScreenCast portal.
2. Grab a single frame, convert it to PNG with Pillow, and save it with 0600 permissions in the session temp dir.
3. Keep the password rule: refuse for a window that shows a password field.
4. Fallback while unavailable: keep the current refusal message.

## Done when
- Window and element screenshots match the window on GNOME, checked by hand.
- The password refusal is still covered by tests.
