# Wayland phase 2: implementation plan

**Status:** 2a, 2b, 2c and 2d scrolling implemented; 2d clicks by position researched, not built
**Date:** 2026-11-22
**Builds on:** [wayland.md](wayland.md), "Phase 2: portal input"

Phase 1 gave the Wayland driver everything AT-SPI can do. Phase 2 adds the
parts that need the compositor's consent: screenshots, key presses, scrolling
and clicks by position, all through xdg-desktop-portal. This plan splits the
work into slices that each ship on their own, ordered so that nothing waits on
the open GNOME focus check except keyboard input itself.

## What was built, and where it differs from the plan

- **2a** is `drivers/portal.py`. The restore token is kept in a `0600` file
  under `$XDG_STATE_HOME/linux-computer-use/` (directory `0700`), not yet in
  libsecret: the file needs no extra typelib and works headless. Moving it to
  the secret store is a small follow-up.
- **2b**: the screenshot is moved out of wherever the portal saved it (GNOME
  saves to `~/Pictures/Screenshots`) into the session's private temp dir, so
  no copy is left behind. On both drivers, `screenshot_desktop` refuses
  while any window shows a password field, and `screenshot_window` /
  `screenshot_element` refuse for a window that shows one. The desktop-wide
  check is one AT-SPI Collection query per window; only apps without
  Collection (GTK 4) get their tree walked.
- **2c**: keyboard input is enabled on GNOME. The user ran
  `tests/manual/focus_check.py` on their GNOME Wayland machine on 2026-11-22
  and reported that it passes: exactly one window claimed focus at each step,
  and it was the one they were in. The raw output wasn't recorded. KDE and
  wlroots stay off (`KEYBOARD_VERIFIED_DESKTOPS` in `drivers/wayland.py`)
  until the same check passes there; `LCU_WAYLAND_KEYBOARD_UNVERIFIED=1` is
  the operator override.
- Known gap from the check: Chrome and Electron apps report no focus unless
  started with accessibility on, so keys to them are refused, never guessed.

## Ground rules

- **Opt-in.** Portal use is off unless the operator sets
  `LCU_WAYLAND_PORTAL=1`. Without it, phase 1 behaviour is unchanged and every
  refusal message says how to turn it on.
- **Refuse, never pretend.** A declined dialog, a rejected restore token, a
  locked screen or a missing portal backend each raise `NotSupportedError`
  with the cause. No action reports success unless the portal accepted it.
- **Guards first.** The password-window check and stale-element check run
  before every portal action, exactly as they do for AT-SPI actions.
- **One session per server.** The server opens at most one RemoteDesktop
  session (with ScreenCast attached) and reuses it, so the user approves once
  per server start, or never again once a restore token is stored.

## Slices

### 2a. Portal session plumbing

New module `drivers/portal.py`, using Gio's D-Bus client from PyGObject, which
the AT-SPI extra already installs. No new dependency.

- `Request`/`Response` handling: every portal call returns a request object
  path; wait for its `Response` signal with a timeout, map response codes
  1 (cancelled) and 2 (other error) to clear messages.
- `PortalSession.open(kinds)`: `CreateSession`, `SelectDevices`
  (keyboard + pointer), `ScreenCast.SelectSources` (monitor), `Start`, with
  `persist_mode=2`.
- Restore tokens: read before `SelectDevices`, replace with the new token
  after every `Start`. Stored through libsecret (`gi.repository.Secret`) when
  available, otherwise a `0600` file in `$XDG_STATE_HOME/linux-computer-use/`,
  matching SECURITY.md's file rules. A rejected token is deleted and the user
  is asked again.
- Session closed by the user (the portal's `Closed` signal): drop it, and the
  next action reports "the user ended the remote control session".
- Capability probe: read `AvailableDeviceTypes` and the portal `version` at
  startup, so refusals can say "this desktop's portal has no RemoteDesktop"
  before a dialog ever appears.

**Tests.** python-dbusmock has no portal template, so tests ship a small fake
`org.freedesktop.portal.Desktop` (RemoteDesktop, ScreenCast, Screenshot,
Request objects) on a private bus. Unit tests cover approve, decline, token
reuse, token rejection, session closed and missing backend. This also answers
the design doc's open question about testing portals in CI.

### 2b. Screenshots (no focus dependency)

- `screenshot_desktop`: the Screenshot portal (`interactive=false`), which
  GNOME and KDE answer with a one-time dialog or a remembered permission.
  Regions are cropped locally with Pillow.
- `screenshot_window`: still refused. Cropping a window out of the desktop
  needs its screen position, which Wayland doesn't give us (see 2d). The
  refusal names that reason and suggests `screenshot_desktop`.
- Sensitive windows: proposed new rule, if any showing window is flagged by
  the password check, `screenshot_desktop` refuses. SECURITY.md lists "never
  write sensitive screenshots to disk", but the X11 path doesn't enforce it
  today, so this should land for both drivers in the same PR.

Lowest risk, read-only, and testable against the fake portal. A good first PR.

### 2c. Keyboard input (gated on the GNOME focus check)

`press_key`, and `type_text` without an element, through
`RemoteDesktop.NotifyKeyboardKeysym`.

**Why keysyms over D-Bus first, not libei.** The design doc recommends
`ConnectToEIS` with `snegg`. Two problems for a first cut: `snegg` has no PyPI
release (checked 2026-11-22), and libei sends evdev keycodes, which makes
`ctrl+c` depend on the user's keyboard layout. `NotifyKeyboardKeysym` takes
X keysyms, so the existing xdotool-style key parser maps straight onto it and
works on any layout. libei stays the follow-up for lower latency and for
pointer input (2d).

**The focus problem.** On Wayland the server cannot focus a window, and key
events go to whatever the compositor has focused. So the safety rule is:

> Before every key event, AT-SPI must report exactly one showing frame as
> `active`, it must be the target window, and the focused element inside it
> must not be a password field. Otherwise refuse.

- `press_key(window_id=N)`: refuse unless window N is the active one; the
  message asks the user to switch to it. `focus_window` stays refused.
- `press_key()` with no window: target whichever window is active; refuse if
  none or more than one claims it.
- Re-check between characters for `type_text` longer than one key chunk, so a
  focus change mid-string stops typing instead of sending the rest elsewhere.

This rule is only safe if GNOME's AT-SPI focus reporting is accurate and
prompt, which is exactly what `focus_check.py` tests. So:

- **Check passes:** build 2c as above, keyboard enabled on GNOME.
- **Check fails:** ship 2c with keyboard refused on GNOME (detected via
  `XDG_CURRENT_DESKTOP`) and record the evidence in wayland.md. KDE gets
  enabled only after the same check passes there.

Until the result is in, 2c's code can be written and unit-tested against the
fake portal, but stays behind the gate.

### 2d. Scrolling and clicks by position

**Scrolling: implemented without a pointer.** `scroll` finds the nearest
showing scroll bar (inside the element, then around each ancestor, stopping
at the window so another window is never touched) and moves its AT-SPI
`Value`, as if the user dragged it. One step is the bar's minimum increment,
or 5% of its range when the toolkit reports none. It refuses when there is no
bar, when the list is already at the end, and when the app ignores the new
value. This works on every compositor and needs no portal. Covered by unit
tests and by a live GTK 3 / GTK 4 test under Weston; widgets without scroll
bars (canvases, some custom lists) still can't be scrolled.

**Clicks by position: not built; recommended route below.** The problem is
mapping AT-SPI's window-relative positions to the coordinates the portal's
pointer uses.

1. **Recommended: a ScreenCast stream of the window itself.** In a combined
   RemoteDesktop + ScreenCast session, `NotifyPointerMotionAbsolute` takes
   coordinates *relative to a stream*. If the stream's source is the target
   window (`SelectSources` with `types=2`, WINDOW), those coordinates are
   window-relative, which is exactly what AT-SPI already gives us, so no
   window origin is needed at all. The user picks the window in the portal
   dialog, and the restore token can bring it back without asking. To
   verify on GNOME and KDE before building: that window streams are accepted
   for pointer events in a RemoteDesktop session, and the offset between the
   stream's content and AT-SPI's window origin (client-side decorations and
   shadows), which may need a one-time calibration from the stream size vs.
   the AT-SPI frame size.
2. **KDE fallback:** a KWin script can report window geometry, giving a
   screen origin for a monitor stream. Usable but KWin-specific.
3. **GNOME fallback:** `org.gnome.Shell.Introspect` is restricted to
   allow-listed callers outside unsafe mode, and matching a window inside a
   monitor-stream frame by size and thumbnail is fragile with overlap and
   scaling. Not recommended.

Either route needs PipeWire only to learn the stream size, not to read
frames. A prototype on a real GNOME session comes before code, because none
of this can run in CI's headless Weston.

**The prototype is `tests/manual/pointer_probe.py`.** It opens the GTK demo,
asks the portal for pointer access and a stream of that one window, moves
the pointer to the "Count" button's centre as AT-SPI reports it, clicks, and
reads the demo's label to see whether the click landed. On a miss it tries
the offsets the stream and frame sizes suggest. Its output decides whether
`click_coordinate` gets built on window streams, and with which offset.

## Order and PRs

| PR | Slice | Waits on |
|---|---|---|
| 1 | 2a portal plumbing + fake portal tests | nothing |
| 2 | 2b desktop screenshots | PR 1 |
| 3 | 2c keyboard input | PR 1, GNOME focus check result |
| 4 | 2d pointer clicks via a window stream | prototype on GNOME |

PRs 1 to 3 and 2d's scrolling landed together in one PR.

Phase 3 (uinput keyboard, `drivers/uinput.py`) landed in the same PR: opt-in with
`LCU_WAYLAND_UINPUT=us`, the same focus and password gate, US layout only.

## What needs a real GNOME or KDE session

None of this can be proven in CI's headless Weston, which has no portal
backend. Before each PR merges, someone runs a short manual script on GNOME
(and KDE when possible): approve the dialog, restart the server and confirm
the token skips it, lock the screen and confirm a clean refusal, then the
slice's own action. Those scripts go in `tests/manual/`.
