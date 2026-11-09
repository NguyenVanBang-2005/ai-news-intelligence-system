import pytest

from app.core.config import settings
from app.services.passwords import hash_password, verify_dummy, verify_password


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "password_scrypt_n", 16)


def test_hash_verifies_only_the_right_password() -> None:
    stored = hash_password("correct horse battery")
    assert stored.startswith("scrypt$16$8$1$")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong horse battery", stored)


def test_same_password_hashes_differently() -> None:
    assert hash_password("same password!") != hash_password("same password!")


def test_old_cost_still_verifies_after_raising_it(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = hash_password("correct horse battery")
    monkeypatch.setattr(settings, "password_scrypt_n", 32)
    assert verify_password("correct horse battery", stored)


def test_malformed_hash_is_rejected() -> None:
    assert not verify_password("anything at all", "not-a-hash")
    assert not verify_password("anything at all", "bcrypt$16$8$1$AAAA$AAAA")


def test_default_cost_runs_within_the_memory_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "password_scrypt_n", 2**15)
    verify_dummy("long enough password")  # would raise ValueError with the default maxmem
