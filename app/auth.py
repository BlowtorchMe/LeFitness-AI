"""
Simple admin authentication helpers.
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from fastapi import Cookie, HTTPException, status

from app.config import settings

ADMIN_COOKIE_NAME = "lefitness_admin_session"
ADMIN_SESSION_MAX_AGE = 60 * 60 * 24 * 7


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def create_admin_session() -> str:
    payload = {
        "admin": True,
        "exp": int(time.time()) + ADMIN_SESSION_MAX_AGE,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(
        settings.admin_session_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).digest()
    return f"{_b64encode(payload_bytes)}.{_b64encode(signature)}"


def verify_admin_session(token: Optional[str]) -> bool:
    if not token or "." not in token:
        return False
    payload_part, signature_part = token.split(".", 1)
    try:
        payload_bytes = _b64decode(payload_part)
        signature = _b64decode(signature_part)
        expected = hmac.new(
            settings.admin_session_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            return False
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return False
    return bool(payload.get("admin")) and int(payload.get("exp", 0)) > int(time.time())


def require_admin(admin_session: Optional[str] = Cookie(default=None, alias=ADMIN_COOKIE_NAME)) -> None:
    if not verify_admin_session(admin_session):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin sign-in required")
