"""Password hashing, attempt limiting, and short-lived admin sessions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
from secrets import token_bytes, token_urlsafe
from threading import Lock
from typing import Callable


PASSWORD_SCHEME = "scrypt-v1"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
HASH_BYTES = 32
MAX_ATTEMPTS = 5
ATTEMPT_WINDOW = timedelta(minutes=10)
LOCK_DURATION = timedelta(minutes=15)
SESSION_DURATION = timedelta(minutes=20)


class AdminPasswordError(ValueError):
    """The supplied password does not meet the local policy."""


class AdminAuthenticationError(RuntimeError):
    """The password or admin session is invalid."""


class AdminRateLimitError(RuntimeError):
    """Too many failed password attempts were made."""


def validate_new_password(value: object) -> str:
    if not isinstance(value, str):
        raise AdminPasswordError("Введите административный пароль.")
    if len(value) < 12:
        raise AdminPasswordError("Пароль должен содержать не менее 12 символов.")
    if len(value) > 256:
        raise AdminPasswordError("Пароль слишком длинный.")
    if not any(character.isalpha() for character in value) or not any(
        character.isdigit() for character in value
    ):
        raise AdminPasswordError("Пароль должен содержать буквы и цифры.")
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
        if len(salt) != SALT_BYTES:
            return False
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        if len(expected) != HASH_BYTES:
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
    expires_at: datetime


class AdminAccessManager:
    """Keep admin tokens and failed attempts only in the local process memory."""

    def __init__(self, *, now_provider: Callable[[], datetime] | None = None) -> None:
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._failed_attempts: deque[datetime] = deque()
        self._locked_until: datetime | None = None
        self._sessions: dict[str, datetime] = {}
        self._lock = Lock()

    def _now(self) -> datetime:
        value = self._now_provider()
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def _cleanup(self, now: datetime) -> None:
        cutoff = now - ATTEMPT_WINDOW
        while self._failed_attempts and self._failed_attempts[0] < cutoff:
            self._failed_attempts.popleft()
        expired = [token for token, expires_at in self._sessions.items() if expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)
        if self._locked_until is not None and self._locked_until <= now:
            self._locked_until = None
            self._failed_attempts.clear()

    def issue_session(self) -> AdminSession:
        with self._lock:
            now = self._now()
            self._cleanup(now)
            token = token_urlsafe(32)
            expires_at = now + SESSION_DURATION
            self._sessions[token] = expires_at
            return AdminSession(token=token, expires_at=expires_at)

    def authenticate(self, password: object, password_hash: str) -> AdminSession:
        with self._lock:
            now = self._now()
            self._cleanup(now)
            if self._locked_until is not None:
                raise AdminRateLimitError(
                    "Слишком много неверных попыток. Повторите вход через 15 минут."
                )
            if not verify_password(password, password_hash):
                self._failed_attempts.append(now)
                if len(self._failed_attempts) >= MAX_ATTEMPTS:
                    self._locked_until = now + LOCK_DURATION
                    raise AdminRateLimitError(
                        "Слишком много неверных попыток. Повторите вход через 15 минут."
                    )
                raise AdminAuthenticationError("Неверный административный пароль.")
            self._failed_attempts.clear()
            token = token_urlsafe(32)
            expires_at = now + SESSION_DURATION
            self._sessions[token] = expires_at
            return AdminSession(token=token, expires_at=expires_at)

    def require(self, token: object) -> None:
        if not isinstance(token, str) or not token:
            raise AdminAuthenticationError("Требуется вход в настройки.")
        with self._lock:
            now = self._now()
            self._cleanup(now)
            expires_at = self._sessions.get(token)
            if expires_at is None or expires_at <= now:
                raise AdminAuthenticationError("Сеанс настроек завершён. Войдите снова.")

    def revoke(self, token: object) -> None:
        if not isinstance(token, str):
            return
        with self._lock:
            self._sessions.pop(token, None)

    def revoke_all(self) -> None:
        with self._lock:
            self._sessions.clear()
