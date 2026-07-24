"""Password hashing and process-local access to administrative settings."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
from secrets import token_bytes, token_urlsafe
from threading import Lock


PASSWORD_SCHEME = "scrypt-v1"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
HASH_BYTES = 32


class AdminPasswordError(ValueError):
    """The supplied password does not meet the local policy."""


class AdminAuthenticationError(RuntimeError):
    """The password or admin session is invalid."""


def validate_new_password(value: object) -> str:
    if not isinstance(value, str):
        raise AdminPasswordError("Введите административный пароль.")
    if not value.strip():
        raise AdminPasswordError("Пароль не может быть пустым.")
    if len(value) > 256:
        raise AdminPasswordError("Пароль слишком длинный.")
    return value


def hash_password(password: object, *, salt: bytes | None = None) -> str:
    normalized = validate_new_password(password)
    effective_salt = salt or token_bytes(SALT_BYTES)
    derived = hashlib.scrypt(
        normalized.encode("utf-8"),
        salt=effective_salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=HASH_BYTES,
    )
    return "$".join(
        (
            PASSWORD_SCHEME,
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.urlsafe_b64encode(effective_salt).decode("ascii"),
            base64.urlsafe_b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: object, encoded: object) -> bool:
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    try:
        scheme, n, r, p, salt_text, digest_text = encoded.split("$")
        if scheme != PASSWORD_SCHEME:
            return False
        if (int(n), int(r), int(p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        if len(salt) != SALT_BYTES or len(expected) != HASH_BYTES:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError, UnicodeEncodeError):
        return False
    return hmac.compare_digest(actual, expected)


@dataclass(frozen=True, slots=True)
class AdminSession:
    token: str


class AdminAccessManager:
    """Keep temporary settings tokens only in the local process memory."""

    def __init__(self) -> None:
        self._sessions: set[str] = set()
        self._lock = Lock()

    def issue_session(self) -> AdminSession:
        with self._lock:
            token = token_urlsafe(32)
            self._sessions.add(token)
            return AdminSession(token=token)

    def authenticate(self, password: object, password_hash: str) -> AdminSession:
        if not verify_password(password, password_hash):
            raise AdminAuthenticationError("Неверный административный пароль.")
        return self.issue_session()

    def require(self, token: object) -> None:
        if not isinstance(token, str) or not token:
            raise AdminAuthenticationError("Требуется вход в настройки.")
        with self._lock:
            if token not in self._sessions:
                raise AdminAuthenticationError("Доступ к настройкам завершён. Откройте их снова.")

    def revoke(self, token: object) -> None:
        if not isinstance(token, str):
            return
        with self._lock:
            self._sessions.discard(token)

    def revoke_all(self) -> None:
        with self._lock:
            self._sessions.clear()
