"""Session management for linux_computer_use."""

from __future__ import annotations

import atexit
import base64
import binascii
import hashlib
import hmac
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROCESS_KEY = os.urandom(32)


def _token_key() -> bytes:
    """HMAC key for element tokens.

    Uses LINUX_COMPUTER_USE_SECRET when set (so tokens survive a restart), and
    otherwise a random per-process key, so tokens can't be forged with a
    well-known default.
    """
    secret = os.environ.get("LINUX_COMPUTER_USE_SECRET")
    return secret.encode() if secret else _PROCESS_KEY


@dataclass
class ElementToken:
    """Element token for secure targeting."""
    window_id: int
    index: int
    snapshot_hash: str
    timestamp: float
    signature: str = field(init=False)

    def __post_init__(self) -> None:
        """Sign the token's fields."""
        self.signature = self._sign()

    def _payload(self) -> str:
        return f"{self.window_id}:{self.index}:{self.snapshot_hash}:{self.timestamp!r}"

    def _sign(self) -> str:
        return hmac.new(_token_key(), self._payload().encode(), hashlib.sha256).hexdigest()

    def to_token(self) -> str:
        """Serialize to an opaque, signed token string."""
        return base64.urlsafe_b64encode(f"{self._payload()}:{self.signature}".encode()).decode()

    @classmethod
    def from_token(cls, token: str) -> ElementToken:
        """Parse and verify a token string. Raises ValueError if malformed or forged."""
        try:
            parts = base64.urlsafe_b64decode(token.encode()).decode().split(":")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("Invalid token format") from exc
        if len(parts) != 5:
            raise ValueError("Invalid token format")

        window_id, index, snapshot_hash, timestamp, signature = parts
        restored = cls(
            window_id=int(window_id),
            index=int(index),
            snapshot_hash=snapshot_hash,
            timestamp=float(timestamp),
        )
        if not hmac.compare_digest(restored.signature, signature):
            raise ValueError("Invalid token signature")
        return restored

    def verify(self) -> bool:
        """Check that the token's fields still match its signature."""
        return hmac.compare_digest(self.signature, self._sign())

    @property
    def expired(self) -> bool:
        """Check if token expired (30 second TTL)."""
        return time.time() - self.timestamp > 30


@dataclass
class WindowInfo:
    """Information about a window."""
    window_id: int
    pid: int
    app_id: str
    title: str
    x: int
    y: int
    width: int
    height: int
    workspace: int
    visible: bool
    app: str = ""


@dataclass
class Element:
    """Element in accessibility tree."""
    index: int
    element_token: str
    role: str
    name: str
    description: str = ""
    state: list[str] = field(default_factory=list)
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    parent_index: int = -1
    children: list[int] = field(default_factory=list)


@dataclass
class WindowState:
    """Complete window state."""
    window_id: int
    pid: int
    screenshot_path: str
    tree_markdown: str
    elements: list[Element]


class Session:
    """Session management for desktop control."""

    def __init__(self, session_id: str | None = None):
        """Initialize session."""
        self.id = session_id or str(uuid.uuid4())
        self.created_at = time.time()
        self.last_activity = time.time()
        self.actions_logged: list[dict[str, Any]] = []
        self._temp_dir = Path(tempfile.gettempdir()) / f"linux-computer-use-{self.id}"
        self._secret = os.urandom(32)

        # Create temp directory
        self._temp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        # Register cleanup
        atexit.register(self.cleanup)

    @property
    def temp_dir(self) -> Path:
        """Get temp directory path."""
        return self._temp_dir

    def audit_action(self, tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        """Log action for security audit."""
        self.actions_logged.append({
            "timestamp": time.time(),
            "tool": tool,
            "args": self._sanitize_args(args),
            "result": result.get("effect"),
            "session_age": time.time() - self.created_at
        })
        self.last_activity = time.time()

    def _sanitize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Remove sensitive data from args."""
        sanitized = {}
        sensitive_keys = {"password", "token", "secret", "key", "credential"}

        for key, value in args.items():
            if key.lower() in sensitive_keys or (isinstance(value, str) and any(
                s in value.lower() for s in sensitive_keys
            )):
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = value

        return sanitized

    def cleanup(self) -> None:
        """Securely clean up session resources."""
        # Securely delete temp files
        if self._temp_dir.exists():
            for filepath in self._temp_dir.iterdir():
                try:
                    # Overwrite with random data
                    size = filepath.stat().st_size
                    with filepath.open("wb") as f:
                        f.write(os.urandom(size))
                    filepath.unlink()
                except Exception:
                    pass

            # Remove directory
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def is_expired(self) -> bool:
        """Check if session expired."""
        return time.time() - self.last_activity > 3600  # 1 hour TTL


# Global session manager
_sessions: dict[str, Session] = {}


def get_active_session() -> Session:
    """Get or create active session."""
    # Return existing session if valid
    for session_id, session in list(_sessions.items()):
        if not session.is_expired():
            return session
        else:
            del _sessions[session_id]

    # Create new session
    new_session = Session()
    _sessions[new_session.id] = new_session
    return new_session
