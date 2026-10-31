from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError


password_hasher = PasswordHasher()
DUMMY_PASSWORD_HASH = password_hasher.hash("dummy-password-for-timing-protection")


def hash_password(plain_password: str) -> str:
    password_hash = password_hasher.hash(plain_password)

    return password_hash


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, VerificationError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return password_hasher.check_needs_rehash(password_hash)
