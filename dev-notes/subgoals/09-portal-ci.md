# 09. Test real portals in CI

**Status:** done. Headless GNOME Shell works in a container: `tests/integration/run_gnome.sh`, `tests/integration/test_gnome_live.py`, and the `gnome-live` CI job (Ubuntu 24.04 container). Dialogs are approved over AT-SPI by `tests/integration/apps/approve_portal.py`. See "Real GNOME in CI" in `docs/design/wayland-phase2.md`. A KDE equivalent (headless KWin) is not tried.
**Depends on:** 01

## Goal
Catch portal regressions without someone running the manual checklist.

## Options
- **Real GNOME in a VM:** a nightly job (self-hosted runner or a nested VM) with a
  headless GNOME Shell (`gnome-shell --headless --wayland`), xdg-desktop-portal-gnome,
  and a pre-approved permission. GNOME's permission store can hold a grant for the
  test app id via `flatpak permission-set`. Not verified that this skips the dialog.
- **xdg-desktop-portal's own test backend:** check whether upstream ships one that
  auto-approves.
- **Keep the fake portal** for every PR, since it already covers our client logic.

## Steps
1. Spike: can headless GNOME Shell run in a GitHub runner container with a
   working RemoteDesktop portal?
2. If yes, add a nightly workflow that runs `tests/manual/portal.md`'s steps as automated tests.
3. If no, document it and keep the manual checklist as the merge gate for portal changes.

## Done when
There's a nightly real-portal job, or a documented decision not to have one.
