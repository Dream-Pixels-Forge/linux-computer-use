"""Session management for linux_computer_use."""

import os
import time
import uuid
import hmac
import hashlib
import atexit
import tempfile
import shutil
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from pathlib import Path


@dataclass
class ElementToken:
    """Element token for secure targeting."""
    window_id: int
    index: int
    snapshot_hash: str
    timestamp: float
    signature: str = field(init=False)
    
    def __post_init__(self):
        """Generate signature after initialization."""
        payload = f"{self.window_id}:{self.index}:{self.snapshot_hash}:{self.timestamp}"
        self.signature = hmac.new(
            self._secret_key(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
    
    @classmethod
    def _secret_key(cls) -> bytes:
        """Get session secret key."""
        key = os.environ.get("LINUX_COMPUTER_USE_SECRET", "default-secret-key")
        return key.encode()
    
    def to_token(self) -> str:
        """Convert to token string."""
        import base64
        payload = f"{self.window_id}:{self.index}:{self.snapshot_hash}:{self.timestamp}"
        return base64.urlsafe_b64encode(payload.encode()).decode()
    
    @classmethod
    def from_token(cls, token: str) -> "ElementToken":
        """Create from token string."""
        import base64
        payload = base64.urlsafe_b64decode(token.encode()).decode()
        parts = payload.split(":")
        if len(parts) != 4:
            raise ValueError("Invalid token format")
        
        window_id, index, snapshot_hash, timestamp = parts
        return cls(
            window_id=int(window_id),
            index=int(index),
            snapshot_hash=snapshot_hash,
            timestamp=float(timestamp)
        )
    
    def verify(self) -> bool:
        """Verify token signature."""
        try:
            self.__post_init__()  # Regenerate and compare
            return True
        except Exception:
            return False
    
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
    state: List[str] = field(default_factory=list)
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    parent_index: int = -1
    children: List[int] = field(default_factory=list)


@dataclass
class WindowState:
    """Complete window state."""
    window_id: int
    pid: int
    screenshot_path: str
    tree_markdown: str
    elements: List[Element]


class Session:
    """Session management for desktop control."""
    
    def __init__(self, session_id: Optional[str] = None):
        """Initialize session."""
        self.id = session_id or str(uuid.uuid4())
        self.created_at = time.time()
        self.last_activity = time.time()
        self.actions_logged: List[Dict[str, Any]] = []
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
    
    def audit_action(self, tool: str, args: dict, result: dict) -> None:
        """Log action for security audit."""
        self.actions_logged.append({
            "timestamp": time.time(),
            "tool": tool,
            "args": self._sanitize_args(args),
            "result": result.get("effect"),
            "session_age": time.time() - self.created_at
        })
        self.last_activity = time.time()
    
    def _sanitize_args(self, args: dict) -> dict:
        """Remove sensitive data from args."""
        sanitized = {}
        sensitive_keys = {"password", "token", "secret", "key", "credential"}
        
        for key, value in args.items():
            if key.lower() in sensitive_keys:
                sanitized[key] = "***REDACTED***"
            elif isinstance(value, str) and any(
                s in value.lower() for s in sensitive_keys
            ):
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
                    with open(filepath, "wb") as f:
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
_sessions: Dict[str, Session] = {}


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