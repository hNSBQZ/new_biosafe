"""Password hashing and signed admin tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

_PASSWORD_ALGORITHM = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 260_000
_TOKEN_VERSION = "v1"


@dataclass(frozen=True)
class AdminTokenPayload:
    username: str
    issued_at: int
    expires_at: int


def hash_password(
    password: str,
    *,
    salt: bytes | None = None,
    iterations: int = _PASSWORD_ITERATIONS,
) -> str:
    salt_bytes = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        iterations,
    )
    return "$".join(
        [
            _PASSWORD_ALGORITHM,
            str(iterations),
            _urlsafe_encode(salt_bytes),
            _urlsafe_encode(digest),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = stored_hash.split("$", 3)
        if algorithm != _PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = _urlsafe_decode(salt_text)
        expected = _urlsafe_decode(digest_text)
    except (ValueError, TypeError):
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return secrets.compare_digest(candidate, expected)


def issue_admin_token(username: str, secret: str, ttl_seconds: int) -> str:
    now = int(time.time())
    payload = AdminTokenPayload(
        username=username,
        issued_at=now,
        expires_at=now + max(1, ttl_seconds),
    )
    payload_b64 = _urlsafe_encode(
        json.dumps(payload.__dict__, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    signature = _signature(secret, payload_b64)
    return ".".join((_TOKEN_VERSION, payload_b64, signature))


def decode_admin_token(token: str, secret: str) -> AdminTokenPayload | None:
    try:
        version, payload_b64, signature = token.split(".", 2)
    except ValueError:
        return None
    if version != _TOKEN_VERSION:
        return None
    if not secrets.compare_digest(signature, _signature(secret, payload_b64)):
        return None
    try:
        payload = json.loads(_urlsafe_decode_text(payload_b64))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        username = str(payload["username"])
        issued_at = int(payload["issued_at"])
        expires_at = int(payload["expires_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if expires_at < int(time.time()):
        return None
    return AdminTokenPayload(username=username, issued_at=issued_at, expires_at=expires_at)


def _signature(secret: str, payload_b64: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return _urlsafe_encode(digest)


def _urlsafe_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _urlsafe_decode(encoded: str) -> bytes:
    return base64.urlsafe_b64decode(_pad_base64(encoded))


def _urlsafe_decode_text(encoded: str) -> str:
    return _urlsafe_decode(encoded).decode("utf-8")


def _pad_base64(value: str) -> str:
    return value + "=" * (-len(value) % 4)
