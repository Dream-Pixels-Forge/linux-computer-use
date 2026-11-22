"""The restore token in a real gnome-keyring, on a private session bus.

Runs in a child process under ``dbus-run-session`` with a throwaway HOME, so
it never touches the developer's own keyring, and so libsecret's cached
session-bus connection can't leak into other tests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from linux_computer_use.drivers import portal

pytestmark = pytest.mark.skipif(
    portal._load_secret() is None
    or not shutil.which("gnome-keyring-daemon")
    or not shutil.which("dbus-run-session"),
    reason="needs gir1.2-secret-1, gnome-keyring and dbus-run-session",
)

CHILD = textwrap.dedent(
    """
    import os, subprocess, sys
    from pathlib import Path
    from linux_computer_use.drivers import portal

    mode = sys.argv[1]
    if mode == "unlocked":
        # Creates and unlocks a "login" keyring, as a desktop login does.
        subprocess.run(["gnome-keyring-daemon", "--unlock", "--components=secrets"],
                       input=b"test-password", check=True, capture_output=True)
    path = Path(os.environ["HOME"]) / "state" / "token"
    old = portal.TokenStore(path, keyring=None)
    old.save("from-file")
    tokens = portal.TokenStore(path)
    assert tokens.keyring is not None
    assert tokens.load() == "from-file"
    if mode == "unlocked":
        assert not path.exists(), "file token should have moved into the keyring"
        tokens.save("from-keyring")
        assert not path.exists()
        assert portal.TokenStore(path).load() == "from-keyring"
        assert portal.Keyring.open().load() == "from-keyring"
        tokens.clear()
        assert portal.Keyring.open().load() is None
    else:
        assert path.exists(), "no unlocked keyring: the file must stay"
        tokens.save("again")
        assert path.read_text() == "again"
    print("ok", mode)
    """
)


@pytest.mark.parametrize("mode", ["unlocked", "no-login-keyring"])
def test_token_in_gnome_keyring(tmp_path: Path, mode: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DBUS_", "GNOME_KEYRING"))}
    env.update(HOME=str(tmp_path), XDG_DATA_HOME=str(tmp_path / "data"),
               XDG_RUNTIME_DIR=str(tmp_path / "run"))
    (tmp_path / "run").mkdir(mode=0o700)
    env.pop(portal.TOKEN_STORE_ENV, None)
    result = subprocess.run(
        ["dbus-run-session", "--", sys.executable, "-c", CHILD, mode],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"ok {mode}" in result.stdout
