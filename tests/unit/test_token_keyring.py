"""Restore token storage: keyring first, file fallback, migration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from linux_computer_use.drivers import portal


class FakeValue:
    def __init__(self, text: str) -> None:
        self.text = text

    def get_text(self) -> str:
        return self.text


class FakeItem:
    def __init__(self, store: FakeService, attrs: dict[str, str], value: str) -> None:
        self.store, self.attrs, self.value = store, attrs, value

    def get_locked(self) -> bool:
        return self.store.locked

    def get_secret(self) -> FakeValue | None:
        return None if self.store.locked else FakeValue(self.value)

    def delete_sync(self, _cancellable: Any) -> None:
        self.store.items.remove(self)


class FakeService:
    def __init__(self) -> None:
        self.items: list[FakeItem] = []
        self.locked = False
        self.reachable = True
        self.has_default = True
        self.searches: list[Any] = []

    def search_sync(self, schema: Any, attrs: dict[str, str], flags: Any, _c: Any) -> list[FakeItem]:
        self.searches.append(flags)
        return [i for i in self.items if i.attrs == attrs]


class FakeCollection:
    def __init__(self, service: FakeService) -> None:
        self.service = service

    def get_locked(self) -> bool:
        return self.service.locked


def fake_secret(service: FakeService) -> SimpleNamespace:
    def get_sync(_flags: Any, _c: Any) -> FakeService:
        if not service.reachable:
            raise RuntimeError("org.freedesktop.secrets was not provided by any .service files")
        return service

    def for_alias_sync(svc: FakeService, alias: str, _f: Any, _c: Any) -> FakeCollection | None:
        assert alias == "default"
        return FakeCollection(svc) if svc.has_default else None

    def create_sync(col: FakeCollection, schema: Any, attrs: dict[str, str], label: str,
                    value: FakeValue, flags: Any, _c: Any) -> None:
        assert flags == "REPLACE"
        assert label == portal.SECRET_LABEL
        col.service.items = [i for i in col.service.items if i.attrs != attrs]
        col.service.items.append(FakeItem(col.service, attrs, value.text))

    return SimpleNamespace(
        Schema=SimpleNamespace(new=lambda name, flags, attrs: (name, attrs)),
        SchemaFlags=SimpleNamespace(NONE=0),
        SchemaAttributeType=SimpleNamespace(STRING="s"),
        Service=SimpleNamespace(get_sync=get_sync),
        ServiceFlags=SimpleNamespace(NONE=0),
        SearchFlags=SimpleNamespace(ALL="ALL", LOAD_SECRETS="LOAD_SECRETS", UNLOCK="UNLOCK"),
        Collection=SimpleNamespace(for_alias_sync=for_alias_sync),
        CollectionFlags=SimpleNamespace(NONE=0),
        COLLECTION_DEFAULT="default",
        Item=SimpleNamespace(create_sync=create_sync),
        ItemCreateFlags=SimpleNamespace(REPLACE="REPLACE"),
        Value=SimpleNamespace(new=lambda text, length, content_type: FakeValue(text)),
    )


@pytest.fixture
def service() -> FakeService:
    return FakeService()


def store(tmp_path: Path, service: FakeService) -> portal.TokenStore:
    return portal.TokenStore(tmp_path / "state" / "token", keyring=portal.Keyring(fake_secret(service)))


def test_token_goes_to_the_keyring_not_the_file(tmp_path: Path, service: FakeService) -> None:
    tokens = store(tmp_path, service)
    tokens.save("abc")
    assert [i.value for i in service.items] == ["abc"]
    assert not tokens.path.exists()
    assert tokens.load() == "abc"
    tokens.save("def")  # replaced, not added
    assert [i.value for i in service.items] == ["def"]
    tokens.clear()
    assert service.items == []
    assert tokens.load() is None


def test_file_token_moves_into_the_keyring(tmp_path: Path, service: FakeService) -> None:
    portal.TokenStore(tmp_path / "state" / "token", keyring=None).save("old")
    tokens = store(tmp_path, service)
    assert tokens.load() == "old"
    assert [i.value for i in service.items] == ["old"]
    assert not tokens.path.exists()


def test_keyring_token_wins_and_stale_file_is_removed(tmp_path: Path, service: FakeService) -> None:
    portal.TokenStore(tmp_path / "state" / "token", keyring=None).save("stale")
    tokens = store(tmp_path, service)
    tokens.keyring.save("fresh")  # type: ignore[union-attr]
    assert tokens.load() == "fresh"
    assert not tokens.path.exists()


@pytest.mark.parametrize("problem", ["unreachable", "locked", "no default keyring"])
def test_falls_back_to_the_file(tmp_path: Path, service: FakeService, problem: str) -> None:
    if problem == "unreachable":
        service.reachable = False
    elif problem == "locked":
        service.locked = True
    else:
        service.has_default = False
    tokens = store(tmp_path, service)
    tokens.save("abc")
    assert service.items == []
    assert tokens.path.stat().st_mode & 0o777 == 0o600
    assert tokens.load() == "abc"
    tokens.clear()
    assert not tokens.path.exists()


def test_locked_keyring_is_never_unlocked(tmp_path: Path, service: FakeService) -> None:
    tokens = store(tmp_path, service)
    tokens.save("abc")
    service.locked = True
    assert tokens.load() is None  # a prompt would block the server; ask the portal again instead
    tokens.clear()
    assert len(service.items) == 1  # locked items are left alone
    assert "UNLOCK" not in service.searches


def test_file_token_stays_when_keyring_cannot_take_it(tmp_path: Path, service: FakeService) -> None:
    portal.TokenStore(tmp_path / "state" / "token", keyring=None).save("old")
    service.has_default = False
    tokens = store(tmp_path, service)
    assert tokens.load() == "old"
    assert tokens.path.exists()


def test_env_forces_the_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(portal, "_load_secret", lambda: pytest.fail("keyring was loaded"))
    monkeypatch.setenv(portal.TOKEN_STORE_ENV, "file")
    assert portal.TokenStore(tmp_path / "t").keyring is None


def test_auto_without_libsecret_uses_the_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(portal.TOKEN_STORE_ENV, raising=False)
    monkeypatch.setattr(portal, "_load_secret", lambda: None)
    tokens = portal.TokenStore(tmp_path / "t")
    assert tokens.keyring is None
    tokens.save("abc")
    assert tokens.load() == "abc"
