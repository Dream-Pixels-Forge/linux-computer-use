#!/usr/bin/env bash
# Run the Wayland integration tests in a throwaway session: a private
# XDG_RUNTIME_DIR, a fresh D-Bus session (the AT-SPI bus starts on demand)
# and headless Weston. Extra arguments go to pytest.
#
#   tests/integration/run_wayland.sh -v
#
# Needs: weston, at-spi2-core, PyGObject in this Python, and a Python with
# GTK 3/4 for the demo apps (LCU_GTK_PYTHON, default /usr/bin/python3).
set -euo pipefail

XDG_RUNTIME_DIR="$(mktemp -d)"
chmod 700 "$XDG_RUNTIME_DIR"
export XDG_RUNTIME_DIR
unset DISPLAY WAYLAND_DISPLAY
trap 'rm -rf "$XDG_RUNTIME_DIR"' EXIT

exec dbus-run-session -- bash -c '
  weston --backend=headless --socket=wayland-1 --width=1280 --height=800 >/dev/null 2>&1 &
  weston_pid=$!
  for _ in $(seq 100); do
    [ -S "$XDG_RUNTIME_DIR/wayland-1" ] && break
    sleep 0.1
  done
  [ -S "$XDG_RUNTIME_DIR/wayland-1" ] || { echo "weston did not start" >&2; exit 1; }
  status=0
  WAYLAND_DISPLAY=wayland-1 python -m pytest tests/integration/test_wayland_live.py "$@" || status=$?
  kill "$weston_pid" 2>/dev/null || true
  exit "$status"
' bash "$@"
