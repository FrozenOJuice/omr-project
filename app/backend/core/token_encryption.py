import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class TokenEncryptionError(ValueError):
    pass


class TokenCipher:
    def __init__(self, secret: str):
        key = hashlib.sha256(f"canvas-token:{secret}".encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise TokenEncryptionError("Unable to decrypt Canvas token") from exc
