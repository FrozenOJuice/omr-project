from argon2 import PasswordHasher

from core.security import hash_password
from core.security import password_needs_rehash
from core.security import verify_password


def test_hash_password_verifies_correct_password():
    password_hash = hash_password("secret-password")

    assert password_hash.startswith("$argon2")
    assert verify_password("secret-password", password_hash)


def test_verify_password_rejects_wrong_password():
    password_hash = hash_password("secret-password")

    assert not verify_password("wrong-password", password_hash)


def test_password_needs_rehash_for_outdated_parameters():
    legacy_hasher = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
    legacy_hash = legacy_hasher.hash("secret-password")

    assert password_needs_rehash(legacy_hash)


def test_password_does_not_need_rehash_for_current_parameters():
    password_hash = hash_password("secret-password")

    assert not password_needs_rehash(password_hash)
