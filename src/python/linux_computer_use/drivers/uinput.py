"""Opt-in virtual keyboard through the kernel's /dev/uinput (phase 3).

For kiosks, CI images and test machines where no desktop portal exists
(most wlroots compositors). The kernel sees a new keyboard, so this works on
any compositor, but with no consent prompt at all, which is why it is off
unless the operator sets ``LCU_WAYLAND_UINPUT=us``:

- **The value names the keyboard layout.** uinput sends physical key codes,
  not characters, so the server must know which layout the desktop uses.
  Only ``us`` is supported; a character the layout can't type is refused.
- **Access is a setup-time decision.** /dev/uinput normally needs root, or a
  udev rule giving a group access. Any process with that access can type
  anywhere, including into a lock screen, so grant it only on machines the
  operator owns.
- **The same guards apply:** keys are only sent after AT-SPI confirms the
  target window has focus and shows no password field (see wayland.py).

Pure Python: the device is set up with ioctl and fed ``input_event``
structs, so there is no dependency on python-evdev or libevdev.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import struct
import time
from collections.abc import Callable
from typing import Any

from linux_computer_use.drivers.base import NotSupportedError

ENABLE_ENV = "LCU_WAYLAND_UINPUT"
DEVICE_PATH = "/dev/uinput"
DEVICE_NAME = b"linux-computer-use virtual keyboard"

# linux/input-event-codes.h
EV_SYN, EV_KEY = 0x00, 0x01
SYN_REPORT = 0
BUS_VIRTUAL = 0x06

# struct input_event on 64-bit Linux: struct timeval (2 x long), __u16 type,
# __u16 code, __s32 value.
_EVENT = struct.Struct("llHHi")
# struct uinput_setup: struct input_id (4 x __u16), char name[80], __u32 ff_effects_max.
_SETUP = struct.Struct("HHHH80sI")


def _ioc(direction: int, kind: str, number: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(kind) << 8) | number


UI_DEV_CREATE = _ioc(0, "U", 1, 0)
UI_DEV_DESTROY = _ioc(0, "U", 2, 0)
UI_DEV_SETUP = _ioc(1, "U", 3, _SETUP.size)
UI_SET_EVBIT = _ioc(1, "U", 100, 4)
UI_SET_KEYBIT = _ioc(1, "U", 101, 4)

KEY_LEFTSHIFT = 42

# --------------------------------------------------------------------------- #
# US layout: keysym -> (evdev key code, needs shift)
# --------------------------------------------------------------------------- #


def _us_layout() -> dict[int, tuple[int, bool]]:
    rows = {
        "1234567890-=": 2, "qwertyuiop[]": 16, "asdfghjkl;'`": 30, "\\zxcvbnm,./": 43,
    }
    shifted = {
        "1234567890-=": "!@#$%^&*()_+", "qwertyuiop[]": "QWERTYUIOP{}",
        "asdfghjkl;'`": 'ASDFGHJKL:"~', "\\zxcvbnm,./": "|ZXCVBNM<>?",
    }
    table: dict[int, tuple[int, bool]] = {}
    for row, first in rows.items():
        for i, (plain, upper) in enumerate(zip(row, shifted[row], strict=True)):
            table[ord(plain)] = (first + i, False)
            table[ord(upper)] = (first + i, True)
    named = {
        0x0020: 57,  # space
        0xFF1B: 1, 0xFF08: 14, 0xFF09: 15, 0xFE20: 15, 0xFF0D: 28, 0xFF8D: 96,
        0xFFE3: 29, 0xFFE4: 97, 0xFFE1: 42, 0xFFE2: 54, 0xFFE9: 56, 0xFFEA: 100,
        0xFFEB: 125, 0xFFEC: 126, 0xFFE5: 58, 0xFF7F: 69, 0xFF14: 70, 0xFF13: 119,
        0xFF61: 99, 0xFF67: 127,
        0xFF50: 102, 0xFF52: 103, 0xFF55: 104, 0xFF51: 105, 0xFF53: 106, 0xFF57: 107,
        0xFF54: 108, 0xFF56: 109, 0xFF63: 110, 0xFFFF: 111,
    }
    for sym, code in named.items():
        table[sym] = (code, False)
    for n in range(1, 25):  # F1..F24
        code = 58 + n if n <= 10 else {11: 87, 12: 88}.get(n, 183 + n - 13)
        table[0xFFBE + n - 1] = (code, False)
    return table


LAYOUTS: dict[str, dict[int, tuple[int, bool]]] = {"us": _us_layout()}


def layout_name(environ: Any = None) -> str | None:
    """The layout the operator enabled uinput for, or None when it is off."""
    env = os.environ if environ is None else environ
    value = (env.get(ENABLE_ENV) or "").strip().lower()
    return value or None


class UInputKeyboard:
    """A virtual keyboard device; ``key()`` matches the portal session's."""

    def __init__(
        self,
        layout: str,
        *,
        path: str = DEVICE_PATH,
        opener: Callable[[str, int], int] = os.open,
        ioctl: Callable[..., Any] = fcntl.ioctl,
        writer: Callable[[int, bytes], int] = os.write,
    ) -> None:
        if layout not in LAYOUTS:
            raise NotSupportedError(
                f"{ENABLE_ENV}={layout!r}: uinput sends physical key codes, so the server "
                f"must know the keyboard layout, and only {', '.join(sorted(LAYOUTS))} is "
                "supported."
            )
        self.layout = LAYOUTS[layout]
        self._ioctl, self._write = ioctl, writer
        self.closed = False
        try:
            self.fd = opener(path, os.O_WRONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            raise NotSupportedError(
                f"{path} doesn't exist; load the uinput kernel module (modprobe uinput)."
            ) from None
        except PermissionError:
            raise NotSupportedError(
                f"No permission to open {path}. Grant it on purpose, e.g. a udev rule "
                'KERNEL=="uinput", GROUP="input", MODE="0660" and add this user to the '
                "group. Anything with that access can type anywhere, including the lock screen."
            ) from None
        try:
            ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            for code in sorted({code for code, _ in self.layout.values()}):
                ioctl(self.fd, UI_SET_KEYBIT, code)
            setup = _SETUP.pack(BUS_VIRTUAL, 0x1D6B, 0x4C43, 1, DEVICE_NAME, 0)
            ioctl(self.fd, UI_DEV_SETUP, setup)
            ioctl(self.fd, UI_DEV_CREATE)
        except OSError as exc:
            os.close(self.fd)
            raise NotSupportedError(f"Could not create the uinput keyboard: {exc}") from None
        # Compositors pick up a new input device asynchronously; events sent
        # in the first moments can be dropped.
        time.sleep(0.2)

    def key(self, keysym: int, *, pressed: bool) -> None:
        """Press or release one keysym, adding shift when the layout needs it."""
        if self.closed:
            raise NotSupportedError("The uinput keyboard was closed.")
        entry = self.layout.get(keysym)
        if entry is None:
            char = chr(keysym) if keysym < 0x110000 else ""
            shown = repr(char) if char.isprintable() and char else f"keysym {keysym:#x}"
            raise NotSupportedError(
                f"{shown} can't be typed with uinput on a US layout; it only sends "
                "physical key codes."
            )
        code, shift = entry
        if pressed:
            if shift:
                self._emit(KEY_LEFTSHIFT, 1)
            self._emit(code, 1)
        else:
            self._emit(code, 0)
            if shift:
                self._emit(KEY_LEFTSHIFT, 0)

    def _emit(self, code: int, value: int) -> None:
        now = time.time()
        sec, usec = int(now), int((now % 1) * 1_000_000)
        try:
            self._write(self.fd, _EVENT.pack(sec, usec, EV_KEY, code, value))
            self._write(self.fd, _EVENT.pack(sec, usec, EV_SYN, SYN_REPORT, 0))
        except OSError as exc:
            raise NotSupportedError(f"Writing to the uinput keyboard failed: {exc}") from None

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        with contextlib.suppress(OSError):
            self._ioctl(self.fd, UI_DEV_DESTROY)
        with contextlib.suppress(OSError):
            os.close(self.fd)


def decode(data: bytes) -> list[tuple[int, int, int]]:
    """(type, code, value) for each input_event in data (for tests)."""
    return [_EVENT.unpack_from(data, i)[2:] for i in range(0, len(data), _EVENT.size)]
