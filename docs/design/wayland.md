# Wayland support: options and recommendation

**Status:** phases 0 and 1 implemented; phase 2 partly implemented (screenshots and keyboard, see [wayland-phase2.md](wayland-phase2.md)); phase 3 proposed
**Date:** 2026-11-21
**Scope:** how `linux-computer-use` can list, read, act on and screenshot windows
on a Wayland desktop. Today `drivers/wayland.py` is a stub: it lists no windows,
returns empty trees and raises on every action.

## Summary

Wayland deliberately does not let one client see or drive another, so no
single mechanism replaces X11 + xdotool. The good news, verified below, is that
**AT-SPI already works on Wayland for most of what an agent does**: reading
trees, clicking buttons through their accessible action, and inserting text.
What AT-SPI cannot do on Wayland is press keys, scroll, or click at a position.
For those, the standard, consented path is the **RemoteDesktop portal with
libei**, which GNOME and KDE implement and wlroots compositors mostly do not.

Recommended plan:

0. **Fix a coordinate bug that already affects X11** (GTK 4 reports every
   element at screen position 0,0). The fix is the same mechanism Wayland
   needs, so it comes first.
1. **AT-SPI-only Wayland driver.** Windows, trees, element clicks, text entry
   and the existing safety guards, with no new permissions and no prompts.
   Tested in CI under headless Weston.
2. **RemoteDesktop portal + libei** for `press_key`, `scroll` and coordinate
   clicks, with a one-time user grant persisted via a restore token.
3. **uinput, opt-in only,** for kiosks and CI machines where no portal exists.

## What Wayland changes, tool by tool

| Tool | X11 today | On Wayland |
|---|---|---|
| `list_windows` | xdotool searches all windows | No cross-desktop window list. AT-SPI lists each app's frames. |
| `get_window_state` | AT-SPI tree + X11 geometry | AT-SPI tree works. **Screen positions are unknown**: elements are window-relative and clients don't know where their window is. |
| `click` (element) | AT-SPI action, else pointer at element centre | AT-SPI action works. Pointer fallback needs injected input *and* the window's screen position. |
| `type_text` | focus, then xdotool types | AT-SPI `EditableText` inserts text directly into fields. Typing into arbitrary focus needs injected input. |
| `press_key` | xdotool | Needs injected input. |
| `scroll` | xdotool wheel | Needs injected input. |
| screenshots | scrot | Screenshot or ScreenCast portal (consent), or compositor tools such as `grim` on wlroots. |

## What we verified

Tested in this repository's dev container on **Weston 13 (headless backend)**
with at-spi2-core 2.52, using `tests/integration/apps/gtk_demo.py` (GTK 3) and
an equivalent GTK 4 app:

| Check | GTK 3.24.41 on Wayland | GTK 4.14.5 on Wayland |
|---|---|---|
| App and frame listed on AT-SPI bus | yes | yes |
| Full element tree | yes | yes (labels expose many clipboard/link actions) |
| Button pressed via accessible `click` action | **works** | **works** |
| `EditableText.insert_text` into an entry | **works** | **works** |
| `Component.grab_focus` | returns true, focus not observed (no keyboard focus in headless Weston) | raises an AT-SPI error |
| Screen-coordinate extents (`CoordType.SCREEN`) | window-relative values (frame at 0,0) | **every element at 0,0** |
| Window-relative extents (`CoordType.WINDOW`) | correct | correct |
| `Collection` interface (used by our password check and big-list fetch) | yes | **no**, so our code falls back to a tree walk |
| `Atspi.generate_keyboard_event` | **reports success, delivers nothing** | (not reached) |
| `Component.scroll_to` | returns false | (not reached) |

The same GTK 4 app on **X11** (Xvfb) also reports every element at screen
position 0,0 after the window was moved to 300,200, while window-relative
extents are correct. This matches upstream reports that GTK 4 no longer
supports screen coordinates over AT-SPI.

Not verified here: GNOME Shell (Mutter) and KWin themselves, Qt, Firefox,
Chromium, Electron and LibreOffice on Wayland, and every portal behaviour
below. Those need a real GNOME or KDE session.

## Input options

### A. AT-SPI only (no injected input)

The app performs the action itself on request over the accessibility bus:
accessible actions (`click`, `press`, `toggle`, `activate`), `EditableText`
(insert, delete, set contents), selection, and value setting for sliders.

- **Works on:** every compositor, since it doesn't involve the compositor.
- **Consent:** none beyond the user running an accessibility-enabled session.
- **Limits:** no key presses or shortcuts, no scrolling, nothing for widgets
  without actions (canvases, games, custom-drawn UIs, some Electron apps).
  `generate_keyboard_event` must **not** be used: on Wayland it reports success
  and delivers nothing.
- **Safety:** acts on the exact widget the agent saw, never on whatever sits
  under a pointer, so our stale-element and password-window guards keep
  working unchanged.

### B. RemoteDesktop portal + libei (`ConnectToEIS`)

`org.freedesktop.portal.RemoteDesktop` creates a session the user approves in
a system dialog. `ConnectToEIS` then returns a file descriptor for a libei
sender, which emits pointer, button, scroll and keyboard (keysym) events. The
portal docs recommend ConnectToEIS over the older per-event D-Bus `Notify*`
methods.

- **Works on:** GNOME and KDE Plasma (6.1+ for libei) through their portal
  backends. **Not** in upstream `xdg-desktop-portal-wlr`; RemoteDesktop for
  wlroots compositors (Sway, Hyprland, river) exists only in open pull requests
  and third-party portals.
- **Consent:** a dialog the first time. With `persist_mode=2` the portal
  returns a `restore_token`; later sessions pass it to skip the dialog, and
  each start returns a new token that must replace the stored one. Reported
  issues: tokens rejected after restarts on some KDE versions, and GNOME
  refusing to create or restore sessions while the screen is locked. Truly
  unattended first use isn't possible; a person must approve once.
- **Positions:** absolute pointer motion is relative to a ScreenCast stream,
  so a ScreenCast session is needed too. That still doesn't say where a given
  window is (see "Coordinates" below).
- **Python:** `snegg` (libei bindings by the libei author) provides
  `Sender.create_for_fd` and a portal helper (`oeffis`).
- **Safety:** matches SECURITY.md's "explicit permission model": the user
  sees and can revoke the grant.

### C. uinput virtual devices (ydotool-style)

Create a kernel virtual keyboard and pointer through `/dev/uinput`.

- **Works on:** any compositor, since input arrives as if from hardware.
- **Consent:** none at runtime, which is the problem. Access to `/dev/uinput`
  needs root or a udev rule and group; any process in that group can type
  anywhere, including into a lock screen.
- **Limits:** emits keycodes, not characters, so typing depends on the
  active keyboard layout. Absolute pointer positioning needs an absolute
  (tablet-style) device and the screen layout; multi-monitor and scaling
  make it fragile. No idea which window is under the pointer.
- **Fit:** kiosks, CI images and dedicated test VMs, where the operator owns
  the machine and opts in explicitly. Never a default.

### D. Compositor-specific virtual input

wlroots' `virtual-pointer` and `virtual-keyboard` protocols (used by `wtype`,
`wlrctl`) on Sway, Hyprland, river and others; KWin's own fake-input and
scripting interfaces; Mutter's private remote-desktop D-Bus API. Each is a
separate backend with its own permission model. Useful later as a fallback
for wlroots, where the portal is missing, but not a first step.

### E. XWayland + xdotool

Only reaches X11 apps running under XWayland. On recent GNOME, XWayland routes
XTEST through the RemoteDesktop portal and libei anyway, so it prompts like
option B. Not a strategy for native Wayland apps.

### Comparison

| | A. AT-SPI | B. Portal + libei | C. uinput | D. Compositor-specific |
|---|---|---|---|---|
| GNOME | yes | yes | yes | private API |
| KDE Plasma | yes | yes (6.1+) | yes | KWin APIs |
| wlroots (Sway, Hyprland…) | yes | not upstream | yes | yes |
| Key presses, shortcuts | no | yes | yes | yes |
| Scroll, coordinate clicks | no | yes, needs window position | yes, needs window position | yes, needs window position |
| User consent | n/a | dialog once, then token | none (setup-time permission) | varies |
| Can type into lock screen | no | no (session refused while locked on GNOME) | **yes** | varies |
| Headless CI | yes (Weston) | hard: needs a dialog approved | yes | wlroots headless |

## Coordinates, window list and screenshots

**Coordinates.** Wayland clients do not know their window's screen position, so
AT-SPI reports positions relative to the window. Anything pointer-based (option
B, C or D) needs the window's origin from somewhere else: the compositor
(GNOME's `org.gnome.Shell.Introspect` is restricted to allow-listed callers
unless the shell runs in unsafe mode; KWin scripting can report it; the wlroots
`foreign-toplevel` protocols list windows but not positions), or by locating
the window in a ScreenCast frame. This is the hardest part of Wayland support
and the main reason to lead with option A.

**Window list.** Use AT-SPI: each application's top-level frames are the
windows, on any compositor. They have no numeric ids, so the driver hands out
per-session ids mapped to the frame's accessible, the same way element indexes
work. `ext-foreign-toplevel-list-v1` gives a standard list on several wlroots-
based compositors and COSMIC, but not on GNOME or KWin.

**Screenshots.** The Screenshot portal works on GNOME and KDE and asks the user
first; whole-screen only. Window or region capture needs a ScreenCast session
(the user picks a window or monitor) and frames from PipeWire. On wlroots,
`grim` captures outputs directly. GNOME Shell's own screenshot D-Bus API is
restricted to allow-listed callers.

## Safety implications

- The password-window guard and stale-element guard are AT-SPI-based and work
  on Wayland unchanged. GTK 4 lacks `Collection`, so the password check falls
  back to a tree walk there; it still runs before every input action.
- Wherever the driver can't act safely (no accessible action, no portal
  grant), it must refuse with a clear error, never report success. This rules
  out `Atspi.generate_keyboard_event`, which silently does nothing on Wayland.
- uinput bypasses compositor focus and permissions entirely. If added, it is
  off unless the operator enables it, and the password-window guard still
  applies before every action.

## Plan

**Phase 0: fix GTK 4 coordinates (affects X11 today).** *(Implemented.)* Read extents with
`CoordType.WINDOW` and add the window's origin, which X11 knows. Today the X11
driver gets every GTK 4 element's position wrong. That affects the pointer
fallback in `click` (elements without a click action), the focus click in
`type_text` when `grab_focus` fails, and `screenshot_element`. (Off-screen
pruning is unaffected: the window and its elements are wrong by the same
offset.) A stray click can land near the top-left of the screen,
possibly in another app. This is the same window-relative model Wayland needs.

**Phase 1: AT-SPI-only Wayland driver.** *(Implemented in `drivers/wayland.py`; tested under headless Weston in CI.)*
- `list_windows` from AT-SPI frames, with per-session ids; `get_window_state`
  from the existing tree reader, positions window-relative.
- `click(element)` via accessible actions only; refuse when there is none.
- `type_text(element)` via `EditableText` (insert at the caret, or set
  contents); refuse for non-editable targets.
- `press_key`, `scroll`, coordinate `click`, screenshots: refuse with an error
  that names what is missing ("needs the RemoteDesktop portal").
- Driver selection: `WAYLAND_DISPLAY` set and no usable `DISPLAY` picks the
  Wayland driver.
- CI: a job running the existing GTK live tests under `weston --backend=headless`
  (shown to work in this container).

**Phase 2: portal input.** *(Screenshots and keyboard implemented; pointer pending.)* RemoteDesktop + ScreenCast sessions through
libei (`snegg`/`oeffis`), restore tokens stored per user in the session's
secret store, and clear errors when the user declines or the token is
rejected. Window origins: KWin script and ScreenCast-frame matching first;
GNOME needs research. Screenshots through ScreenCast.
The slice-by-slice plan is in [wayland-phase2.md](wayland-phase2.md).

**Phase 3: optional uinput backend** behind an explicit setting, for kiosk and
CI use.

## Open questions

- How to get a window's screen position on GNOME without unsafe mode. This
  decides whether coordinate clicks are feasible there.
- Whether Qt 6, Firefox, Chromium/Electron and LibreOffice expose working
  accessible actions and `EditableText` on Wayland, as GTK does.
- How to test portal flows in CI, where nobody can approve a dialog:
  `xdg-desktop-portal` test backends, or a nightly job on a real GNOME VM.
- Whether to keep window ids stable across server restarts (AT-SPI frames have
  no persistent id).

## Sources

- [RemoteDesktop portal documentation](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html) and [interface XML](https://github.com/flatpak/xdg-desktop-portal/blob/main/data/org.freedesktop.portal.RemoteDesktop.xml): `ConnectToEIS`, `persist_mode`, restore tokens
- [xdg-desktop-portal-kde: RemoteDesktop version 2 (persistence)](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/merge_requests/223); KDE bugs [480235](https://bugs.kde.org/show_bug.cgi?id=480235), [517454](https://bugs.kde.org/show_bug.cgi?id=517454), [493139](https://bugs.kde.org/show_bug.cgi?id=493139)
- [Lamco RDP platform compatibility](https://lamco.ai/products/lamco-rdp-server/platforms/) (vendor claim: GNOME and KDE 6.1+ input through portal + libei)
- wlroots / Hyprland RemoteDesktop work in progress: [xdg-desktop-portal-wlr #263](https://www.github.com/emersion/xdg-desktop-portal-wlr/pull/263), [xdg-desktop-portal-hyprland #402](https://github.com/hyprwm/xdg-desktop-portal-hyprland/pull/402), [#426](https://github.com/hyprwm/xdg-desktop-portal-hyprland/pull/426), [#448](https://github.com/hyprwm/xdg-desktop-portal-hyprland/pull/448)
- [Unattended remote desktop on Wayland](https://pinggy.io/blog/remote_desktop_into_wayland_without_a_vps/) (GNOME refusing sessions while locked; anecdotal); [GNOME Discourse: allow-listing a binary for the portal](https://discourse.gnome.org/t/be-able-to-whitelist-a-binary-to-have-access-to-the-remote-desktop-portal-without-confirmation-dialogue/27614)
- GTK 4 and AT-SPI coordinates: [accerciser MR 33](https://gitlab.gnome.org/GNOME/accerciser/-/merge_requests/33), [GTK #5896](https://gitlab.gnome.org/GNOME/gtk/-/issues/5896), [GTK #6343](https://gitlab.gnome.org/GNOME/gtk/-/issues/6343), [at-spi2-core #72](https://gitlab.gnome.org/GNOME/at-spi2-core/-/issues/72), [GTK #5149](https://gitlab.gnome.org/GNOME/gtk/-/issues/5149)
- [`ext-foreign-toplevel-list-v1`](https://wayland.app/protocols/ext-foreign-toplevel-list-v1); [KDE bug 483227](https://bugs.kde.org/show_bug.cgi?id=483227)
- GNOME Shell restricted D-Bus APIs: [introspect: use unsafe-mode](https://mail.gnome.org/archives/commits-list/2021-September/msg01053.html), [request for a public Introspect API](https://gitlab.gnome.org/GNOME/gnome-shell/-/issues/5446)
- XWayland XTEST through libei: [KWin MR 5619](https://invent.kde.org/plasma/kwin/-/merge_requests/5619), [OpenJDK wakefield-dev thread](https://mail.openjdk.org/pipermail/wakefield-dev/2025-March/000198.html), [xdotool on Wayland](https://semicomplete.com/blog/xdotool-and-exploring-wayland-fragmentation/)
- uinput: [ydotool man page](https://man.archlinux.org/man/ydotool.1), [KeePass: Auto-Type on Wayland](https://keepass.info/help/kb/autotype_wayland.html)
- libei Python bindings: [snegg.ei](https://libinput.pages.freedesktop.org/snegg/snegg.ei.html), [snegg.oeffis](https://libinput.pages.freedesktop.org/snegg/snegg.oeffis.html)
