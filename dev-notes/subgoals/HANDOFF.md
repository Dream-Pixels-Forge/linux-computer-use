# Handoff: Wayland support

**Date:** 2026-11-22
**Branch / PR:** `claude/project-thread-sdx9uf`, PR #6 (ready for review, CI green on all 6 checks)
**Read first:** `docs/design/wayland.md` (options and phases), `docs/design/wayland-phase2.md` (what was built and why)

## Where things stand

| Phase | What | State |
|---|---|---|
| 0 | GTK 4 coordinates fix | merged (PR #4) |
| 1 | AT-SPI-only Wayland driver | merged (PR #5) |
| 2a | Portal client (`drivers/portal.py`) | in PR #6 |
| 2b | Desktop screenshots via the Screenshot portal | in PR #6 |
| 2c | Keyboard via RemoteDesktop `NotifyKeyboardKeysym` | in PR #6, enabled on GNOME only |
| 2d | Scrolling via AT-SPI scroll bar `Value` | in PR #6 |
| 2d | Clicks by position | **not built**; probe script ready |
| 3 | uinput keyboard (`drivers/uinput.py`) | in PR #6; uinput pointer not built |

Every new capability is opt-in:

| Variable | Effect |
|---|---|
| `LCU_WAYLAND_PORTAL=1` | portal screenshots and keyboard |
| `LCU_WAYLAND_KEYBOARD_UNVERIFIED=1` | allow keyboard on desktops not in `KEYBOARD_VERIFIED_DESKTOPS` |
| `LCU_WAYLAND_UINPUT=us` | keys via `/dev/uinput` instead of the portal (US layout only) |

## Safety rules that must survive any change

- A key is sent only when exactly one window reports `active` over AT-SPI, it is
  the target, and it shows no password field. Typing re-checks every 16 characters.
- A desktop joins `KEYBOARD_VERIFIED_DESKTOPS` (`drivers/wayland.py`) only after
  `tests/manual/focus_check.py` passes on it. GNOME passed on 2026-11-22, as
  reported by the user (raw output not recorded). KDE has not been checked.
- Screenshots refuse while a password window is showing (desktop), or for a
  window that shows one (window and element shots), on both drivers.
- Never report success unless the portal, AT-SPI or the kernel accepted the action.
- Never use `Atspi.generate_keyboard_event` on Wayland: it reports success and
  delivers nothing.

## How to run things

```bash
pip install -e ".[dev,atspi]"
ruff check src/python tests && mypy src/python && pytest tests/unit
dbus-run-session -- xvfb-run -a pytest tests/integration      # X11 live + fake portal
tests/integration/run_wayland.sh                               # Wayland live under Weston
```

- In the cloud container, PyGObject only works with `python3.12`. Make a venv with
  `--system-site-packages`. GTK 3/4, Weston, at-spi2-core, xdotool, scrot and xterm
  can be installed with apt (run `apt-get update` first). Set `LCU_GTK_PYTHON=/usr/bin/python3.12`.
- CI has no real portal and no `/dev/uinput`. Real behaviour is checked by hand
  with `tests/manual/portal.md`.

## Gotchas learned the hard way

- `gi.repository` loads typelibs lazily: import `gi.repository.Gio` by name
  (regression test: `test_gio_loads_in_a_fresh_process`).
- `Gio.TestDBus` unsets `DISPLAY` in the C environment, so tests restore `os.environ` afterwards.
- Subscribe to portal `Session.Closed` without a sender filter. GDBus drops
  signals that arrive before it has resolved a well-known name.
- GTK puts a scroll pane's bars beside a long list. Walk up checking only direct
  children, or the search budget runs out on the rows.

## Next steps

One file per subgoal in this folder, in suggested order:

1. [01-verify-and-merge-pr6.md](01-verify-and-merge-pr6.md): needs the user's GNOME machine
2. [02-clicks-by-position.md](02-clicks-by-position.md): blocked on the pointer probe output
3. [03-kde-keyboard.md](03-kde-keyboard.md)
4. [04-window-screenshots.md](04-window-screenshots.md)
5. [05-toolkit-coverage.md](05-toolkit-coverage.md)
6. [06-wlroots-desktops.md](06-wlroots-desktops.md)
7. [07-uinput-hardening.md](07-uinput-hardening.md)
8. [08-restore-token-in-keyring.md](08-restore-token-in-keyring.md)
9. [09-portal-ci.md](09-portal-ci.md)
10. [10-stable-window-ids.md](10-stable-window-ids.md)
