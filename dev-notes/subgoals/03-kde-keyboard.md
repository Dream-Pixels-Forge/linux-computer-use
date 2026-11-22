# 03. Enable keyboard input on KDE Plasma

**Status:** not started
**Depends on:** 01 (merged code)
**Needs:** a KDE Plasma 6 Wayland session

## Goal
Add `kde` to `KEYBOARD_VERIFIED_DESKTOPS`, backed by evidence.

## Steps
1. Run `python3 tests/manual/focus_check.py` on Plasma for 20 seconds while
   switching between an editor, a terminal and a file manager. **Save the raw output.**
2. Pass criteria (in the script's docstring): exactly one window reports focus,
   it's the right one, and it updates within about a second.
3. If it passes, run the keyboard steps of `tests/manual/portal.md` on KDE.
   Note any restore-token problems (KDE bugs 480235, 517454).
4. Add `"kde"` to `KEYBOARD_VERIFIED_DESKTOPS`, with the date and evidence in the
   comment and in `docs/design/wayland-phase2.md`.

## Done when
- The focus check output is committed or linked.
- The portal checklist passes on KDE.
- `kde` is in the set with a dated note.

## If it fails
Keep KDE off and record the failure mode in the design doc.
