# 06. wlroots desktops (Sway, Hyprland, river)

**Status:** not started
**Depends on:** 01

## Goal
Useful input and screenshots on wlroots compositors, where upstream
`xdg-desktop-portal-wlr` has no RemoteDesktop.

## Options (design doc, option D)
- **Keyboard:** the `virtual-keyboard-unstable-v1` protocol (as `wtype` does), or
  the uinput keyboard already built (`LCU_WAYLAND_UINPUT=us`).
- **Screenshots:** `grim` via the wlroots screencopy protocol, or the Screenshot
  portal from `xdg-desktop-portal-wlr`.
- **Window list:** `ext-foreign-toplevel-list-v1` / `wlr-foreign-toplevel`. Not
  needed while AT-SPI frames work.

## Steps
1. Run the focus check on Sway. Keyboard gating relies on AT-SPI `active`,
   which Sway doesn't control, so verify it like any other desktop.
2. Try the uinput keyboard on Sway in a VM, and record results.
3. Decide whether a `wtype`-style backend is worth it over uinput. It's layout-aware and needs no `/dev/uinput` access.
4. Screenshot through the wlr Screenshot portal, which the existing client already supports.

## Done when
Sway has a documented, tested path for keys and screenshots, or a documented reason why not.
