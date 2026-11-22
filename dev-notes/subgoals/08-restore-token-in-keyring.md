# 08. Keep the portal restore token in the keyring

**Status:** done (branch `claude/project-thread-sdx9uf`, after PR #6). Real KDE/KWallet not tried: KWallet answers the same Secret Service API since KF 5.97, but check by hand with step 6 of `tests/manual/portal.md`.
**Depends on:** 01

## Goal
Move the RemoteDesktop restore token from a 0600 file
(`$XDG_STATE_HOME/linux-computer-use/remote-desktop-token`) into the user's
secret store, through libsecret.

## Steps
1. In `portal.TokenStore`, use `gi.repository.Secret` when its typelib is present,
   with a schema like `dev.lcu.RemoteDesktopToken`.
2. Keep the file as a fallback for headless machines with no secret service.
3. Migrate an existing file token on first load, then delete the file.
4. Tests: unit tests with a fake Secret module. A live test if `gnome-keyring` can
   run headless in CI; otherwise test by hand.

## Done when
The token is in the keyring on GNOME and KDE, with a file fallback, and tests cover both paths.
