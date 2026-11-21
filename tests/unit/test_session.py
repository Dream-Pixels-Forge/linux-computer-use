"""Unit tests for session management."""

import time

import pytest
from linux_computer_use.session import ElementToken, Session, get_active_session


class TestElementToken:
    """Tests for element token generation and verification."""

    def test_token_creation(self):
        """Test element token creation."""
        token = ElementToken(
            window_id=1,
            index=5,
            snapshot_hash="abc123",
            timestamp=time.time()
        )

        assert token.window_id == 1
        assert token.index == 5
        assert token.snapshot_hash == "abc123"
        assert token.signature is not None
        assert len(token.signature) == 64  # SHA256 hex digest

    def test_token_roundtrip(self):
        """Test token can be serialized and deserialized."""
        original = ElementToken(
            window_id=42,
            index=100,
            snapshot_hash="deadbeef",
            timestamp=time.time()
        )

        token_str = original.to_token()
        restored = ElementToken.from_token(token_str)

        assert restored.window_id == original.window_id
        assert restored.index == original.index
        assert restored.snapshot_hash == original.snapshot_hash

    def test_token_not_expired(self):
        """Test valid token is not expired."""
        token = ElementToken(
            window_id=1,
            index=1,
            snapshot_hash="test",
            timestamp=time.time()
        )

        assert not token.expired

    def test_token_expired(self):
        """Test expired token."""
        token = ElementToken(
            window_id=1,
            index=1,
            snapshot_hash="test",
            timestamp=time.time() - 31  # 31 seconds ago
        )

        assert token.expired

    def test_forged_token_rejected(self):
        """A token whose fields were edited fails signature verification."""
        import base64

        token = ElementToken(window_id=1, index=2, snapshot_hash="h", timestamp=time.time())
        fields = base64.urlsafe_b64decode(token.to_token()).decode().split(":")
        fields[1] = "99"  # retarget another element, keep the old signature
        forged = base64.urlsafe_b64encode(":".join(fields).encode()).decode()
        with pytest.raises(ValueError, match="signature"):
            ElementToken.from_token(forged)

    def test_unsigned_token_rejected(self):
        """A token without a signature is rejected."""
        import base64

        unsigned = base64.urlsafe_b64encode(b"1:2:h:123.0").decode()
        with pytest.raises(ValueError):
            ElementToken.from_token(unsigned)

    def test_verify_detects_tampering(self):
        token = ElementToken(window_id=1, index=2, snapshot_hash="h", timestamp=time.time())
        assert token.verify()
        token.index = 3
        assert not token.verify()

    def test_invalid_token_format(self):
        """Test invalid token raises error."""
        with pytest.raises(ValueError):
            ElementToken.from_token("not-a-valid-token!!!")


class TestSession:
    """Tests for session management."""

    def test_session_creation(self):
        """Test session is created correctly."""
        session = Session()

        assert session.id is not None
        assert len(session.id) == 36  # UUID format
        assert session.created_at is not None
        assert session.last_activity is not None

    def test_session_temp_dir(self):
        """Test temp directory is created."""
        session = Session()

        assert session.temp_dir.exists()
        assert session.temp_dir.name.startswith("linux-computer-use-")

    def test_session_cleanup(self):
        """Test session cleanup removes temp files."""
        session = Session()

        # Create temp files
        test_file = session.temp_dir / "test.txt"
        test_file.write_text("test data")

        assert test_file.exists()

        # Cleanup
        session.cleanup()

        assert not session.temp_dir.exists()

    def test_session_audit(self):
        """Test action auditing."""
        session = Session()

        session.audit_action("test_tool", {"key": "value"}, {"effect": "success"})

        assert len(session.actions_logged) == 1
        assert session.actions_logged[0]["tool"] == "test_tool"
        assert session.last_activity > session.created_at

    def test_session_sanitize_args(self):
        """Test argument sanitization."""
        session = Session()

        # Test sensitive key is redacted
        result = session._sanitize_args({"password": "secret"})
        assert result["password"] == "***REDACTED***"

        result = session._sanitize_args({"token": "abc123"})
        assert result["token"] == "***REDACTED***"

        # Test normal args pass through
        result = session._sanitize_args({"element": 5, "window_id": 1})
        assert result["element"] == 5
        assert result["window_id"] == 1

    def test_session_not_expired(self):
        """Test fresh session is not expired."""
        session = Session()
        assert not session.is_expired()

    def test_session_expired(self):
        """Test old session is expired."""
        session = Session()
        # Force expiry by setting old last_activity
        session.last_activity = time.time() - 3700  # 1 hour + 100 seconds

        assert session.is_expired()


class TestSessionManager:
    """Tests for session manager functions."""

    def test_get_active_session_returns_session(self):
        """Test get_active_session returns valid session."""
        session = get_active_session()

        assert isinstance(session, Session)
        assert session.id is not None

    def test_get_active_session_returns_same_session(self):
        """Test get_active_session returns same session."""
        session1 = get_active_session()
        session2 = get_active_session()

        # Should be same session (within TTL)
        assert session1.id == session2.id
