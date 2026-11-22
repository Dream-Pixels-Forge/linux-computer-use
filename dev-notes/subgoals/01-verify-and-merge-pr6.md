# 01. Verify PR #6 on real GNOME, then merge

**Status:** waiting on the user
**Depends on:** nothing
**Needs:** the user's GNOME Wayland machine

## Goal
Confirm that the portal screenshot and keyboard paths, and the uinput keyboard,
work on real hardware, then merge PR #6.

## Steps
1. Run the 9 steps in `tests/manual/portal.md` on GNOME with `LCU_WAYLAND_PORTAL=1`.
2. Run `python3 tests/manual/pointer_probe.py` and paste its full output in the PR (this feeds subgoal 02).
3. Optional, on a spare machine: the uinput section of `tests/manual/portal.md`.
4. Fix anything that fails, re-run CI, and merge.

## Done when
- Every step in the checklist passes, or each failure has a fix in the PR.
- The desktop, GNOME version and results are recorded in the PR.
- PR #6 is merged.

## Watch for
- Whether GNOME's Screenshot portal shows a dialog for an unsandboxed app (unverified).
- Whether a RemoteDesktop session with only a keyboard, and no ScreenCast, is accepted on GNOME (unverified).
- Lock screen: the session must be refused cleanly, never report success.
