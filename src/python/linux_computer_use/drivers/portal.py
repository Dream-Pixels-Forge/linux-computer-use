"""xdg-desktop-portal client for Wayland screenshots and keyboard input.

On Wayland a program may only capture the screen or send input through the
desktop portal, which asks the user first. This module talks to
``org.freedesktop.portal.Desktop`` over D-Bus with Gio (from PyGObject, which
the AT-SPI support already needs), so it adds no dependency.

- ``Portal.screenshot()``: the Screenshot portal. The image is moved out of
  wherever the portal saved it (often ~/Pictures) into our private temp dir.
- ``Portal.remote_desktop()``: one RemoteDesktop session with a keyboard,
  opened on first use and reused. ``persist_mode=2`` makes the portal return
  a restore token, kept in the desktop keyring (or a ``0600`` file when
  there is none), so later server starts skip the dialog.

Every failure (no portal, the user declined, the session was closed, a
timeout) raises :class:`PortalError`, a ``NotSupportedError``, with the cause.
Nothing here reports success unless the portal said so.

The portal is only used when ``LCU_WAYLAND_PORTAL=1``; see
docs/design/wayland-phase2.md.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import os
import secrets
import shutil
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from linux_computer_use.drivers.base import NotSupportedError

logger = logging.getLogger(__name__)

BUS_NAME = "org.freedesktop.portal.Desktop"
OBJECT_PATH = "/org/freedesktop/portal/desktop"
REQUEST_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"
SCREENSHOT_IFACE = "org.freedesktop.portal.Screenshot"
REMOTE_DESKTOP_IFACE = "org.freedesktop.portal.RemoteDesktop"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

#: RemoteDesktop device types.
KEYBOARD = 1
POINTER = 2

#: How long to wait for a portal answer. Calls that may show a dialog wait
#: long enough for a person to read it and decide.
CALL_TIMEOUT = 10.0
DIALOG_TIMEOUT = 90.0

ENABLE_ENV = "LCU_WAYLAND_PORTAL"

OPT_IN_HINT = (
    f"Set {ENABLE_ENV}=1 to let this server ask, through your desktop's portal, "
    "for permission to do it."
)


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    """True when the operator opted in to portal use."""
    env = os.environ if environ is None else environ
    return truthy(env.get(ENABLE_ENV))


class PortalError(NotSupportedError):
    """The portal refused, failed or isn't there; the message says which."""


_ENDED = (
    "The remote control session was ended (by you or the desktop). The next action will "
    "ask for permission again."
)


# --------------------------------------------------------------------------- #
# Restore tokens
# --------------------------------------------------------------------------- #

#: libsecret schema name and the attributes that find our one item.
SECRET_SCHEMA = "dev.lcu.RemoteDesktopToken"
SECRET_ATTRIBUTES = {"purpose": "remote-desktop-restore-token"}
SECRET_LABEL = "linux-computer-use remote desktop permission"

#: ``LCU_TOKEN_STORE=file`` keeps the token in the file even when a keyring exists.
TOKEN_STORE_ENV = "LCU_TOKEN_STORE"


def _load_secret() -> Any | None:
    try:
        gi = importlib.import_module("gi")
        gi.require_version("Secret", "1")
        return importlib.import_module("gi.repository.Secret")
    except (ImportError, ValueError):
        return None


class Keyring:
    """The restore token in the desktop's secret store, through libsecret.

    It never asks the user to unlock anything: a locked keyring counts as
    unavailable, and :class:`TokenStore` falls back to its file.
    """

    def __init__(self, secret: Any) -> None:
        self._secret = secret
        self._schema = secret.Schema.new(
            SECRET_SCHEMA,
            secret.SchemaFlags.NONE,
            dict.fromkeys(SECRET_ATTRIBUTES, secret.SchemaAttributeType.STRING),
        )

    @classmethod
    def open(cls) -> Keyring | None:
        """A keyring backend, or None when libsecret's typelib isn't installed."""
        secret = _load_secret()
        return cls(secret) if secret is not None else None

    def _service(self) -> Any:
        return self._secret.Service.get_sync(self._secret.ServiceFlags.NONE, None)

    def _items(self, flags: Any) -> list[Any]:
        # No SearchFlags.UNLOCK: unlocking would pop up a password prompt.
        return list(
            self._service().search_sync(self._schema, dict(SECRET_ATTRIBUTES), flags, None) or []
        )

    def load(self) -> str | None:
        for item in self._items(self._secret.SearchFlags.LOAD_SECRETS):
            if item.get_locked():
                continue
            value = item.get_secret()
            text = value.get_text() if value is not None else None
            if text and text.strip():
                return str(text).strip()
        return None

    def save(self, token: str) -> None:
        secret = self._secret
        collection = secret.Collection.for_alias_sync(
            self._service(), secret.COLLECTION_DEFAULT, secret.CollectionFlags.NONE, None
        )
        if collection is None:
            raise RuntimeError("the secret service has no default keyring")
        if collection.get_locked():
            raise RuntimeError("the default keyring is locked")
        secret.Item.create_sync(
            collection,
            self._schema,
            dict(SECRET_ATTRIBUTES),
            SECRET_LABEL,
            secret.Value.new(token, len(token.encode()), "text/plain"),
            secret.ItemCreateFlags.REPLACE,
            None,
        )

    def clear(self) -> None:
        for item in self._items(self._secret.SearchFlags.ALL):
            if not item.get_locked():
                item.delete_sync(None)


class TokenStore:
    """The RemoteDesktop restore token.

    A restore token lets a later session skip the permission dialog, so it is
    treated like a credential. It lives in the desktop keyring (libsecret)
    when one is reachable and unlocked; otherwise in a 0600 file in a 0700
    directory under XDG_STATE_HOME. A token found in the file is moved into
    the keyring on first load, and the file is deleted.

    ``keyring="auto"`` uses libsecret when its typelib is installed, unless
    ``LCU_TOKEN_STORE=file``; ``keyring=None`` uses only the file.
    """

    def __init__(self, path: Path | None = None, keyring: Keyring | str | None = "auto") -> None:
        if path is None:
            state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
            path = Path(state) / "linux-computer-use" / "remote-desktop-token"
        self.path = path
        if keyring == "auto":
            use_file = os.environ.get(TOKEN_STORE_ENV, "").strip().lower() == "file"
            keyring = None if use_file else Keyring.open()
        if isinstance(keyring, str):
            raise ValueError(f"keyring must be 'auto', None or a Keyring, not {keyring!r}")
        self.keyring: Keyring | None = keyring

    # The keyring is optional: any failure there (no secret service, locked,
    # D-Bus error) is logged and the file is used instead.

    def _keyring_load(self) -> tuple[bool, str | None]:
        if self.keyring is None:
            return False, None
        try:
            return True, self.keyring.load()
        except Exception as exc:
            logger.debug("keyring unavailable for loading: %s", exc)
            return False, None

    def _keyring_save(self, token: str) -> bool:
        if self.keyring is None:
            return False
        try:
            self.keyring.save(token)
        except Exception as exc:
            logger.debug("keyring unavailable for saving: %s", exc)
            return False
        return True

    def load(self) -> str | None:
        reachable, token = self._keyring_load()
        if token:
            self._clear_file()  # a leftover file token is older than the keyring's
            return token
        file_token = self._load_file()
        if file_token and reachable and self._keyring_save(file_token):
            self._clear_file()
        return file_token

    def save(self, token: str) -> None:
        if self._keyring_save(token):
            self._clear_file()
        else:
            self._save_file(token)

    def clear(self) -> None:
        if self.keyring is not None:
            try:
                self.keyring.clear()
            except Exception as exc:
                logger.debug("keyring unavailable for clearing: %s", exc)
        self._clear_file()

    def _load_file(self) -> str | None:
        try:
            token = self.path.read_text().strip()
        except OSError:
            return None
        return token or None

    def _save_file(self, token: str) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token)
        self.path.chmod(0o600)

    def _clear_file(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


# --------------------------------------------------------------------------- #
# Portal client
# --------------------------------------------------------------------------- #


def _load_gio() -> tuple[Any, Any] | None:
    # Import the submodules by name: gi.repository loads typelibs lazily, so
    # its attributes don't exist until each one is imported.
    try:
        return (
            importlib.import_module("gi.repository.Gio"),
            importlib.import_module("gi.repository.GLib"),
        )
    except (ImportError, ValueError):
        return None


class RemoteDesktopSession:
    """An approved RemoteDesktop session that can send keysyms."""

    def __init__(self, portal: Portal, handle: str, devices: int) -> None:
        self.portal = portal
        self.handle = handle
        self.devices = devices
        self.closed = False

    def key(self, keysym: int, *, pressed: bool) -> None:
        """Press or release one keysym."""
        if self.closed:
            raise PortalError(_ENDED)
        if not self.devices & KEYBOARD:
            raise PortalError("The permission you granted doesn't include the keyboard.")
        try:
            self.portal.call(
                REMOTE_DESKTOP_IFACE,
                "NotifyKeyboardKeysym",
                self.portal.glib.Variant("(oa{sv}iu)", (self.handle, {}, keysym, int(pressed))),
            )
        except PortalError as exc:
            # The session was refused: most likely ended before its Closed
            # signal reached us. Start afresh next time.
            self.closed = True
            raise PortalError(f"{_ENDED} ({exc})") from None

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        with contextlib.suppress(PortalError):
            self.portal.call(SESSION_IFACE, "Close", None, path=self.handle)


class Portal:
    """Synchronous wrapper over the desktop portal's request/response calls.

    Calls are made asynchronously and the GLib main context is iterated until
    the reply arrives, so this works from a thread that runs no main loop, and
    in tests where the fake portal lives in the same process.
    """

    def __init__(
        self,
        tokens: TokenStore | None = None,
        bus_address: str | None = None,
        temp_dir: Callable[[], Path] | None = None,
    ) -> None:
        self.tokens = tokens or TokenStore()
        self._bus_address = bus_address
        self._temp_dir = temp_dir
        self._bus: Any = None
        self._session: RemoteDesktopSession | None = None
        gio = _load_gio()
        self.gio: Any = gio[0] if gio else None
        self.glib: Any = gio[1] if gio else None

    # -- plumbing ----------------------------------------------------------- #

    def bus(self) -> Any:
        if self.gio is None:
            raise PortalError("Portal access needs PyGObject (pip install PyGObject).")
        if self._bus is None:
            gio = self.gio
            try:
                if self._bus_address:
                    self._bus = gio.DBusConnection.new_for_address_sync(
                        self._bus_address,
                        gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                        | gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                        None,
                        None,
                    )
                else:
                    self._bus = gio.bus_get_sync(gio.BusType.SESSION, None)
            except Exception as exc:
                raise PortalError(f"Could not reach the D-Bus session bus: {exc}") from None
        return self._bus

    def _iterate(self) -> bool:
        """Run one non-blocking GLib main context iteration."""
        return bool(self.glib.MainContext.default().iteration(may_block=False))

    def _wait(self, done: Callable[[], bool], timeout: float) -> bool:
        end = time.monotonic() + timeout
        while not done():
            if time.monotonic() > end:
                return False
            if not self._iterate():
                time.sleep(0.005)
        return True

    def call(
        self,
        iface: str,
        method: str,
        args: Any,
        *,
        path: str = OBJECT_PATH,
        reply_type: str | None = None,
        timeout: float = CALL_TIMEOUT,
    ) -> Any:
        """Call a portal method and return its unpacked reply."""
        bus = self.bus()
        box: dict[str, Any] = {}

        def finished(conn: Any, result: Any) -> None:
            try:
                box["value"] = conn.call_finish(result)
            except Exception as exc:  # GLib.Error
                box["error"] = exc

        bus.call(
            BUS_NAME, path, iface, method, args,
            self.glib.VariantType.new(reply_type) if reply_type else None,
            self.gio.DBusCallFlags.NONE, int(timeout * 1000), None, finished,
        )
        if not self._wait(lambda: bool(box), timeout + 1):
            raise PortalError(f"The desktop portal didn't answer {method} in time.")
        if "error" in box:
            raise PortalError(_describe_error(method, box["error"]))
        return box["value"].unpack() if box["value"] is not None else None

    def _sender_path(self, kind: str, token: str) -> str:
        sender = self.bus().get_unique_name().lstrip(":").replace(".", "_")
        return f"{OBJECT_PATH}/{kind}/{sender}/{token}"

    def request(
        self,
        iface: str,
        method: str,
        build_args: Callable[[str], Any],
        *,
        timeout: float = CALL_TIMEOUT,
    ) -> dict[str, Any]:
        """Call a method that answers through a Request object's Response signal.

        ``build_args(handle_token)`` returns the call's arguments. Returns the
        response's results; raises PortalError if the user cancelled or the
        portal failed.
        """
        bus = self.bus()
        token = "lcu_" + secrets.token_hex(8)
        expected = self._sender_path("request", token)
        box: dict[str, Any] = {}

        def on_response(_c: Any, _s: Any, path: str, _i: Any, _sig: Any, params: Any) -> None:
            if path in (expected, box.get("path")):
                box["response"] = params.unpack()

        sub = bus.signal_subscribe(
            BUS_NAME, REQUEST_IFACE, "Response", None, None,
            self.gio.DBusSignalFlags.NONE, on_response,
        )
        try:
            (handle,) = self.call(iface, method, build_args(token), reply_type="(o)")
            box["path"] = handle
            if not self._wait(lambda: "response" in box, timeout):
                with contextlib.suppress(PortalError):
                    self.call(REQUEST_IFACE, "Close", None, path=handle)
                raise PortalError(
                    f"No answer to the desktop's {_friendly(method)} request within "
                    f"{int(timeout)} seconds."
                )
        finally:
            bus.signal_unsubscribe(sub)
        code, results = box["response"]
        if code == 1:
            raise PortalError(f"The {_friendly(method)} request was declined.")
        if code != 0:
            raise PortalError(
                f"The desktop portal couldn't complete the {_friendly(method)} request."
            )
        return dict(results)

    def get_property(self, iface: str, name: str) -> Any:
        (value,) = self.call(
            PROPERTIES_IFACE, "Get", self.glib.Variant("(ss)", (iface, name)), reply_type="(v)"
        )
        return value

    # -- Screenshot --------------------------------------------------------- #

    def screenshot(self) -> str:
        """Capture the whole screen; return the path of a PNG we own."""
        variant = self._variant()
        no = variant("b", False)  # noqa: FBT003  (GLib.Variant value)
        results = self.request(
            SCREENSHOT_IFACE,
            "Screenshot",
            lambda t: variant("(sa{sv})", ("", {"handle_token": variant("s", t), "interactive": no})),
            timeout=DIALOG_TIMEOUT,
        )
        uri = results.get("uri")
        if not uri:
            raise PortalError("The screenshot portal returned no image.")
        source = Path(unquote(urlparse(str(uri)).path))
        if not source.is_file():
            raise PortalError("The screenshot portal's image could not be read.")
        # The portal may have saved it into the user's Pictures folder; keep
        # no copy there, since it may show something private.
        target_dir = self._temp_dir() if self._temp_dir else source.parent
        target = target_dir / f"portal_{secrets.token_hex(6)}{source.suffix or '.png'}"
        shutil.move(str(source), target)
        target.chmod(0o600)
        return str(target)

    # -- RemoteDesktop ------------------------------------------------------ #

    def remote_desktop(self) -> RemoteDesktopSession:
        """The keyboard session, asking the user for permission if needed."""
        if self._session is not None and not self._session.closed:
            return self._session
        variant = self._variant()
        try:
            version = int(self.get_property(REMOTE_DESKTOP_IFACE, "version"))
            available = int(self.get_property(REMOTE_DESKTOP_IFACE, "AvailableDeviceTypes"))
        except PortalError as exc:
            if "No desktop portal is running" in str(exc):
                raise
            raise PortalError(
                "This desktop's portal has no RemoteDesktop support, so keys can't be "
                "sent. GNOME and KDE Plasma provide it; most wlroots desktops (Sway, "
                "Hyprland) don't yet."
            ) from None
        if not available & KEYBOARD:
            raise PortalError("This desktop's RemoteDesktop portal offers no keyboard.")

        session_token = "lcu_s" + secrets.token_hex(8)
        created = self.request(
            REMOTE_DESKTOP_IFACE,
            "CreateSession",
            lambda t: variant(
                "(a{sv})",
                ({"handle_token": variant("s", t),
                  "session_handle_token": variant("s", session_token)},),
            ),
        )
        handle = str(created.get("session_handle") or self._sender_path("session", session_token))
        restore = self.tokens.load() if version >= 2 else None

        def select(t: str) -> Any:
            options = {"handle_token": variant("s", t), "types": variant("u", KEYBOARD)}
            if version >= 2:
                options["persist_mode"] = variant("u", 2)
                if restore:
                    options["restore_token"] = variant("s", restore)
            return variant("(oa{sv})", (handle, options))

        try:
            self.request(REMOTE_DESKTOP_IFACE, "SelectDevices", select)
            started = self.request(
                REMOTE_DESKTOP_IFACE,
                "Start",
                lambda t: variant("(osa{sv})", (handle, "", {"handle_token": variant("s", t)})),
                timeout=DIALOG_TIMEOUT,
            )
        except PortalError as exc:
            if restore:
                # The stored grant may be what was rejected; ask afresh next time.
                self.tokens.clear()
            with contextlib.suppress(PortalError):
                self.call(SESSION_IFACE, "Close", None, path=handle)
            raise PortalError(
                f"Permission to send keys wasn't granted: {exc} GNOME also refuses while "
                "the screen is locked."
            ) from None

        new_token = started.get("restore_token")
        if new_token:
            self.tokens.save(str(new_token))
        elif restore:
            self.tokens.clear()  # tokens are single-use; the old one is spent
        session = RemoteDesktopSession(self, handle, int(started.get("devices", 0)))

        def on_closed(*_args: Any) -> None:
            session.closed = True

        # No sender filter: GDBus resolves a well-known sender name to its
        # owner asynchronously and can drop a signal that arrives first. The
        # path is ours alone, and a spoofed Closed only makes us stop.
        self.bus().signal_subscribe(
            None, SESSION_IFACE, "Closed", handle, None,
            self.gio.DBusSignalFlags.NONE, on_closed,
        )
        self._session = session
        return session

    def pump(self) -> None:
        """Deliver pending D-Bus signals (e.g. the session being closed)."""
        if self.glib is not None:
            while self._iterate():
                pass

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def _variant(self) -> Any:
        self.bus()  # fails early without PyGObject or a session bus
        return self.glib.Variant


def _friendly(method: str) -> str:
    return {
        "Screenshot": "screenshot",
        "CreateSession": "remote control",
        "SelectDevices": "remote control",
        "Start": "remote control",
    }.get(method, method)


def _describe_error(method: str, exc: Exception) -> str:
    text = str(exc)
    if "ServiceUnknown" in text or "was not provided by any" in text:
        return (
            "No desktop portal is running (org.freedesktop.portal.Desktop). Install "
            "xdg-desktop-portal and your desktop's backend (xdg-desktop-portal-gnome or "
            "-kde)."
        )
    if "UnknownMethod" in text or "UnknownInterface" in text or "No such interface" in text:
        return f"This desktop's portal doesn't support {method}."
    return f"The desktop portal failed on {method}: {text}"
