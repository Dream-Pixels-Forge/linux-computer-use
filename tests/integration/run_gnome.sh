#!/usr/bin/env bash
# Run the real-GNOME portal tests: headless GNOME Shell, xdg-desktop-portal
# with the GNOME backend, PipeWire, all in a throwaway HOME and D-Bus session.
# Extra arguments go to pytest.
#
#   sudo tests/integration/run_gnome.sh -v      # or as root in a container
#
# Needs: gnome-shell, xdg-desktop-portal(-gnome), pipewire, wireplumber,
# at-spi2-core, python-dbusmock and PyGObject in this Python, and a Python
# with GTK 4 for the demo apps (LCU_GTK_PYTHON).
#
# Outside a desktop login (a container, CI) there's no system bus or logind,
# which GNOME Shell needs: this starts a system bus and a python-dbusmock
# logind when they're missing, which needs root.
set -euo pipefail

PYTHON="${PYTHON:-python}"
cleanup=()
trap 'for pid in "${cleanup[@]}"; do kill "$pid" 2>/dev/null || true; done' EXIT

if [ ! -S /run/dbus/system_bus_socket ]; then
  mkdir -p /run/dbus
  dbus-daemon --system --fork --print-pid > /run/dbus/lcu-test.pid
fi
if ! gdbus introspect --system -d org.freedesktop.login1 -o /org/freedesktop/login1 >/dev/null 2>&1; then
  "$PYTHON" -m dbusmock --system --template logind >/dev/null 2>&1 &
  cleanup+=("$!")
  for _ in $(seq 50); do
    gdbus introspect --system -d org.freedesktop.login1 -o /org/freedesktop/login1 >/dev/null 2>&1 && break
    sleep 0.2
  done
fi

HOME="$(mktemp -d)"
XDG_RUNTIME_DIR="$(mktemp -d)"
chmod 700 "$XDG_RUNTIME_DIR"
export HOME XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP=GNOME XDG_SESSION_TYPE=wayland PYTHON
unset DISPLAY WAYLAND_DISPLAY
trap 'for pid in "${cleanup[@]}"; do kill "$pid" 2>/dev/null || true; done; rm -rf "$HOME" "$XDG_RUNTIME_DIR"' EXIT
LOGS="${LCU_GNOME_LOGS:-$XDG_RUNTIME_DIR/logs}"
mkdir -p "$LOGS"
export LOGS

dbus-run-session -- bash -c '
  set -u
  pids=()
  stop() { for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; }
  trap stop EXIT
  wait_for() {  # wait_for <what> <command...>
    local what=$1; shift
    for _ in $(seq 150); do "$@" >/dev/null 2>&1 && return 0; sleep 0.2; done
    echo "$what did not start; logs in $LOGS" >&2; exit 1
  }
  has_name() { gdbus call --session -d org.freedesktop.DBus -o /org/freedesktop/DBus \
                 -m org.freedesktop.DBus.NameHasOwner "$1" | grep -q true; }

  pipewire >"$LOGS/pipewire.log" 2>&1 & pids+=($!)
  wireplumber >"$LOGS/wireplumber.log" 2>&1 & pids+=($!)
  # --unsafe-mode lets the tests focus windows with org.gnome.Shell.Eval.
  gnome-shell --headless --wayland --no-x11 --unsafe-mode --virtual-monitor 1280x720 \
    >"$LOGS/gnome-shell.log" 2>&1 & pids+=($!)
  wait_for "GNOME Shell" test -S "$XDG_RUNTIME_DIR/wayland-0"
  wait_for "GNOME Shell D-Bus" has_name org.gnome.Shell
  export WAYLAND_DISPLAY=wayland-0
  # Start the portals by hand, after the shell: started earlier by D-Bus
  # activation, they come up without RemoteDesktop.
  /usr/libexec/xdg-desktop-portal-gnome -r >"$LOGS/portal-gnome.log" 2>&1 & pids+=($!)
  wait_for "xdg-desktop-portal-gnome" has_name org.freedesktop.impl.portal.desktop.gnome
  /usr/libexec/xdg-desktop-portal -r >"$LOGS/portal.log" 2>&1 & pids+=($!)
  wait_for "xdg-desktop-portal" has_name org.freedesktop.portal.Desktop
  LCU_GNOME_LIVE=1 "$PYTHON" -m pytest tests/integration/test_gnome_live.py "$@"
' bash "$@"
