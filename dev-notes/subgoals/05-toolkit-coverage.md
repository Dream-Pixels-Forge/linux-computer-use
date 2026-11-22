# 05. Toolkit coverage beyond GTK

**Status:** not started
**Depends on:** nothing (can run in CI or the cloud container)

## Goal
Know which features work for Qt 6, Firefox, Chromium/Electron and LibreOffice
on Wayland, and test each one that should.

## Check per toolkit
- Frame listed, tree readable, positions window-relative.
- Accessible click action on buttons.
- `EditableText` insertion into a text field.
- Scroll bar `Value` scrolling (the new `scroll` path).
- `active` state on the focused window (the keyboard gate depends on it).
- Password fields reported as `password text`.

## Steps
1. Add small demo apps under `tests/integration/apps/`: a Qt 6 app (PySide6 or
   `qml`) and a static HTML page for Firefox and Chromium (with `--force-renderer-accessibility`).
2. Extend `test_wayland_live.py` with per-toolkit parameters. Skip a toolkit if it isn't installed.
3. Add the packages to the Weston CI job if they install in reasonable time.
4. Record a support matrix in `docs/design/wayland.md`.

## Done when
There's a matrix in the docs and live tests for every toolkit that supports a
feature. Unsupported features refuse with a clear message.
