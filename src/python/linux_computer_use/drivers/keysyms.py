"""xdotool-style key names to X keysyms, for portal keyboard input.

The RemoteDesktop portal's ``NotifyKeyboardKeysym`` takes X keysyms, which
name a symbol rather than a physical key, so ``ctrl+c`` means the same thing
on every keyboard layout. This module turns the server's key syntax
(``"Return"``, ``"ctrl+shift+t"``, ``"alt+F4"``) and plain text into keysyms
without needing GDK or libxkbcommon.
"""

from __future__ import annotations

#: Modifier aliases accepted in combinations, mapped to the left-hand keysym.
MODIFIERS: dict[str, int] = {
    "ctrl": 0xFFE3, "control": 0xFFE3, "control_l": 0xFFE3, "control_r": 0xFFE4,
    "shift": 0xFFE1, "shift_l": 0xFFE1, "shift_r": 0xFFE2,
    "alt": 0xFFE9, "alt_l": 0xFFE9, "alt_r": 0xFFEA,
    "super": 0xFFEB, "super_l": 0xFFEB, "super_r": 0xFFEC, "meta": 0xFFEB, "win": 0xFFEB,
}

#: Named keys, by lower-case xdotool / X keysym name.
NAMED: dict[str, int] = {
    "return": 0xFF0D, "enter": 0xFF0D, "kp_enter": 0xFF8D,
    "tab": 0xFF09, "iso_left_tab": 0xFE20,
    "escape": 0xFF1B, "esc": 0xFF1B,
    "backspace": 0xFF08,
    "delete": 0xFFFF, "del": 0xFFFF,
    "insert": 0xFF63,
    "home": 0xFF50, "end": 0xFF57,
    "page_up": 0xFF55, "prior": 0xFF55, "pageup": 0xFF55,
    "page_down": 0xFF56, "next": 0xFF56, "pagedown": 0xFF56,
    "left": 0xFF51, "up": 0xFF52, "right": 0xFF53, "down": 0xFF54,
    "space": 0x0020,
    "menu": 0xFF67,
    "print": 0xFF61,
    "caps_lock": 0xFFE5, "num_lock": 0xFF7F, "scroll_lock": 0xFF14,
    "pause": 0xFF13,
    "minus": 0x002D, "plus": 0x002B, "equal": 0x003D,
    "comma": 0x002C, "period": 0x002E, "slash": 0x002F, "backslash": 0x005C,
    "semicolon": 0x003B, "apostrophe": 0x0027, "grave": 0x0060,
    "bracketleft": 0x005B, "bracketright": 0x005D,
}
NAMED.update({f"f{n}": 0xFFBE + n - 1 for n in range(1, 25)})

#: Characters typed as their own named key rather than a Unicode keysym.
_CHAR_KEYS = {"\n": 0xFF0D, "\t": 0xFF09, "\b": 0xFF08}


class KeyNameError(ValueError):
    """A key name this module doesn't know."""


def char_keysym(char: str) -> int:
    """The keysym that types one character."""
    if char in _CHAR_KEYS:
        return _CHAR_KEYS[char]
    code = ord(char)
    if 0x20 <= code <= 0x7E or 0xA0 <= code <= 0xFF:
        return code  # Latin-1 keysyms equal their code point
    if code < 0x20 or code == 0x7F:
        raise KeyNameError(f"Control character {code:#x} can't be typed.")
    return 0x01000000 | code  # X11 Unicode keysym


def key_keysym(name: str) -> int:
    """The keysym for one key name, e.g. "Return", "F4", "a", "ctrl"."""
    lower = name.lower()
    if lower in MODIFIERS:
        return MODIFIERS[lower]
    if lower in NAMED:
        return NAMED[lower]
    if len(name) == 1:
        return char_keysym(name)
    raise KeyNameError(f"Unknown key {name!r}.")


def parse_combo(keys: str) -> list[int]:
    """Keysyms for a combination, modifiers first: "ctrl+shift+t" -> [ctrl, shift, t].

    The keys are pressed in this order and released in reverse. A lone "+"
    is the plus key.
    """
    keys = keys.strip()
    if not keys:
        raise KeyNameError("No key given.")
    if keys == "+":
        return [NAMED["plus"]]
    if keys.endswith("++"):  # "ctrl++" is ctrl and the plus key
        head = keys[:-2]
        parts = [*(head.split("+") if head else []), "plus"]
    else:
        parts = keys.split("+")
    if any(not p for p in parts):
        raise KeyNameError(f"Malformed key combination {keys!r}.")
    *mods, last = parts
    for m in mods:
        if m.lower() not in MODIFIERS:
            raise KeyNameError(f"{m!r} in {keys!r} is not a modifier (ctrl, shift, alt, super).")
    return [MODIFIERS[m.lower()] for m in mods] + [key_keysym(last)]


def text_keysyms(text: str) -> list[int]:
    """One keysym per character of text."""
    return [char_keysym(c) for c in text]
