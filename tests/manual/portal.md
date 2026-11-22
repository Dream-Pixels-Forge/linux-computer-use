# Manual check: portal screenshots and keyboard on a real desktop

CI only has a fake portal and headless Weston, which has no portal backend.
Run this on a GNOME (and, when possible, KDE) Wayland session before merging
changes to `drivers/portal.py` or the Wayland keyboard path. About 5 minutes.

Start the server with the portal enabled, connected to an MCP client of your
choice (or `npx @modelcontextprotocol/inspector`):

```bash
LCU_WAYLAND_PORTAL=1 python -m linux_computer_use.mcp
```

Open gedit or GNOME Text Editor with an empty document, and a terminal.

| # | Do | Expect |
|---|---|---|
| 1 | `screenshot_desktop` | A permission prompt the first time (or none, if already allowed); then an image of the screen. **Nothing new in `~/Pictures/Screenshots`.** |
| 2 | Open a password prompt (e.g. `zenity --password`), then `screenshot_desktop` | Refused: "showing a password field". Close the prompt. |
| 3 | `list_windows`; click into the editor; `press_key` `{"keys": "a", "window_id": <editor>}` | The RemoteDesktop dialog appears. Approve it. An `a` appears in the editor. |
| 4 | `type_text` `{"text": "Hello, Wayland", "window_id": <editor>}` | The text appears in the editor, no dialog. |
| 5 | Click into the terminal; `press_key` `{"keys": "Return", "window_id": <editor>}` | Refused: window doesn't have keyboard focus; names the terminal. Nothing typed anywhere. |
| 6 | Restart the server; click into the editor; repeat step 3 | **No dialog** (restore token reused). `secret-tool search purpose remote-desktop-restore-token` shows the token, and `~/.local/state/linux-computer-use/remote-desktop-token` does not exist. |
| 7 | Stop the remote session from the desktop (GNOME: the screen-sharing indicator in the top bar). Then repeat step 4 | Refused: "session was ended". The next call asks again. |
| 8 | Lock the screen, wait, unlock; clear the token (`secret-tool clear purpose remote-desktop-restore-token`, and delete the token file if any); repeat step 3 while locked (use a timer: `sleep 10; ...`) | Refused with a clear reason, never "success". |
| 9 | `press_key` `{"keys": "ctrl+a"}` then `{"keys": "BackSpace"}` in the editor | Text selected, then deleted (modifiers released afterwards: typing still works normally). |

Record the desktop, version and result in the PR. On a desktop not yet in
`KEYBOARD_VERIFIED_DESKTOPS`, run `python3 tests/manual/focus_check.py`
first (instructions in the script) and set
`LCU_WAYLAND_KEYBOARD_UNVERIFIED=1` for steps 3 to 9.

## Clicks by position: pointer probe

```bash
python3 tests/manual/pointer_probe.py
```

Pick the "LCU Pointer Probe" window in the portal dialog. Paste the whole
output into the PR: the `RESULT:` line says whether window-stream clicks
work and with which offset.

## uinput keyboard (kiosk / no portal)

On a machine where you can grant `/dev/uinput` access (and may type into the
lock screen by accident, so not your daily desktop):

```bash
sudo modprobe uinput
LCU_WAYLAND_UINPUT=us LCU_WAYLAND_KEYBOARD_UNVERIFIED=1 python -m linux_computer_use.mcp
```

Repeat steps 3 to 5 and 9 above (no dialog appears). `type_text` with `é`
must be refused before anything is typed.
