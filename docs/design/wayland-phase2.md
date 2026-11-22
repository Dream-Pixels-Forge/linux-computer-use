# Wayland phase 2: implementation plan

**Status:** proposed
**Date:** 2026-11-22
**Builds on:** [wayland.md](wayland.md), "Phase 2: portal input"

Phase 1 gave the Wayland driver everything AT-SPI can do. Phase 2 adds the
parts that need the compositor's consent: screenshots, key presses, scrolling
and clicks by position, all through xdg-desktop-portal. This plan splits the
work into slices that each ship on their own, ordered so that nothing waits on
the open GNOME focus check except keyboard input itself.

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

### 2d. Pointer input: scroll and coordinate clicks (needs research)

Needs the window's screen origin, which is still the design doc's hardest open
question. Proposed order:

1. **Scroll without a position first.** Try `Component.scroll_to` and
   `ScrollPane` values over AT-SPI for scroll-to-element, which needs no
   pointer. Phase 1 saw `scroll_to` return false on GTK 3 under Weston; retest
   on GNOME before relying on it.
2. **KWin:** a KWin script reports window geometry; usable on KDE.
3. **GNOME:** no allowed API without unsafe mode. Option worth prototyping:
   locate the window in a ScreenCast frame by matching the AT-SPI window size
   and a thumbnail. Fragile with overlap and scaling, so it ships only if a
   prototype is reliable.

Pointer events then go through `NotifyPointerMotionAbsolute` on the
ScreenCast stream and `NotifyPointerAxisDiscrete` for wheel steps. This slice
is a research spike before it is a PR.

## Order and PRs

| PR | Slice | Waits on |
|---|---|---|
| 1 | 2a portal plumbing + fake portal tests | nothing |
| 2 | 2b desktop screenshots | PR 1 |
| 3 | 2c keyboard input | PR 1, GNOME focus check result |
| 4 | 2d scroll and pointer | PR 1, research spike |

Phase 3 (uinput) is unaffected by this plan.

## What needs a real GNOME or KDE session

None of this can be proven in CI's headless Weston, which has no portal
backend. Before each PR merges, someone runs a short manual script on GNOME
(and KDE when possible): approve the dialog, restart the server and confirm
the token skips it, lock the screen and confirm a clean refusal, then the
slice's own action. Those scripts go in `tests/manual/`.
