# Goal: 12-toolkit-coverage (Issue #12, subgoal 05)

**Branch:** `feature/12-wayland-toolkit-coverage`
**Worktree:** `/tmp/lcu-issue-12` (git worktree of the `linux-computer-use` repo)
**Depends on:** nothing; previous subgoals (GTK 3/4 under headless Weston) already land in CI.

## Objective

Know which Wayland features work for **Qt 6, Firefox, Chromium/Electron and LibreOffice**, and test each one that should be tested. Record a truthful support matrix in `docs/design/wayland.md`; never mark an unrun path as working.

## Scope (subgoal 05 only)

- Add a small **Qt 6 demo app** under `tests/integration/apps/` (PySide6, same widget set as the GTK demos: Count button, clicks label, editable entry, password entry, long scrolled row list).
- Add a **static HTML fixture** under `tests/integration/apps/` for Firefox and Chromium (same widget set, plain HTML/JS, no build step).
- Extend `tests/integration/test_wayland_live.py` with per-toolkit parameters; each toolkit skips when its runtime isn't installed.
- Add installable packages to the Weston CI job only when they install in reasonable time (`python3-pyside6` for Qt 6).
- Record the support matrix + blockers in `docs/design/wayland.md`.
- Unsupported features refuse with a clear message (already the driver's behaviour; the tests assert the refusals where they apply).

## Out of scope (do not touch)

- No pointer input, no uinput, no window-stream/screen-position work (phase 2d stays untouched).
- No driver changes: the Wayland driver already does AT-SPI click, EditableText, scroll-by-value and the password guard.
- No push, no PR, no changes to `main`.
- Not addressed here: GNOME/KDE portal flows (phase 2), XWayland apps.

## Per-toolkit checks (each toolkit that is installed)

1. Frame listed, tree readable, positions window-relative (`source == "atspi"`, `coordinates == "window"`).
2. Button has an accessible click action; clicking it changes the demo.
3. `EditableText.insert_text` into an entry; value reflects it.
4. Scroll bar `Value` scrolling moves the long list.
5. Exactly one frame reports `active` (the keyboard gate depends on it).
6. Password field reported as role `password text`, `value is None`, and typing into it is refused.

## What "tested" means in the matrix

| mark | meaning |
|---|---|
| `yes` | Live test ran under headless Weston and passed (in this repo's CI or locally). |
| `planned` | Test exists and skips when the runtime is missing; not yet run here (documented blocker). |
| `no` | Refused with a clear message; verified by the refusal test. |

## Blockers to document (not add broken CI jobs for)

- **Weston is not installed in this environment and apt needs root**, so live RED/GREEN can only be captured where a local Weston can be stood up; CI runs the real job.
- **Electron**: no Electron runtime available; no reasonable CI package; skip + blocker note.
- **Chromium**: not installed locally; `--force-renderer-accessibility` needed; unrun under Weston → blocker note unless a CI run verifies it.
- **LibreOffice**: `soffice` + `libreoffice-gtk3` exist locally, but AT-SPI exposure under headless Weston is unverified → test added, skip-if-missing, blocker note until a run verifies it.
- **Firefox**: needs `MOZ_ENABLE_WAYLAND=1` and a fresh profile; unrun under Weston → blocker note until verified.

## Definition of done

- [ ] `dev-notes/goals/12-toolkit-coverage.md` exists (this file) with a short plan.
- [ ] `tests/integration/apps/qt6_demo.py` and `tests/integration/apps/demo.html` exist.
- [ ] `test_wayland_live.py` parameterized over all six toolkits; GTK unchanged; others skip when missing.
- [ ] RED captured before the apps/fixture land; checks run after.
- [ ] `.github/workflows/ci.yml` wayland job installs `python3-pyside6` only (reasonable deps).
- [ ] `docs/design/wayland.md` has the truthful matrix + blocker notes.
- [ ] `ruff check`, `mypy`, unit tests pass.
- [ ] Commit on `feature/12-wayland-toolkit-coverage` referencing #12; no push, no main.
