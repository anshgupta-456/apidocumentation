"""Optional admin authentication.

Enabled when ADMIN_PASSWORD is set. The dashboard uses an HMAC-signed, HttpOnly session
cookie; scripts / CI can send `X-API-Key: <ADMIN_API_KEY>` (or `Authorization: Bearer ...`).
The monitored business API (/api/...) and /health always stay public.
"""
import base64
import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import HTTPException, Request

from app.config import settings

COOKIE_NAME = "acv_session"
_MAX_ATTEMPTS = 8
_WINDOW_SECONDS = 300
_attempts = defaultdict(deque)
_attempts_lock = threading.Lock()


class LoginRequired(Exception):
    def __init__(self, next_url: str = "/ui"):
        self.next_url = next_url


def _secret() -> bytes:
    if settings.SECRET_KEY:
        return settings.SECRET_KEY.encode()
    # Stable across restarts without extra configuration; changing the password logs everyone out.
    return hashlib.sha256(f"acv-session::{settings.ADMIN_PASSWORD}".encode()).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_session_token(username: str) -> str:
    expires = int(time.time()) + settings.SESSION_HOURS * 3600
    payload = f"{username}|{expires}".encode()
    signature = hmac.new(_secret(), payload, hashlib.sha256).hexdigest()
    return f"{_b64(payload)}.{signature}"


def verify_session_token(token: Optional[str]) -> Optional[str]:
    if not token or "." not in token:
        return None
    encoded, signature = token.rsplit(".", 1)
    try:
        payload = _unb64(encoded)
    except (ValueError, TypeError):
        return None
    expected = hmac.new(_secret(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        username, expires = payload.decode().rsplit("|", 1)
        if int(expires) < time.time():
            return None
    except ValueError:
        return None
    return username


def check_credentials(username: str, password: str) -> bool:
    user_ok = hmac.compare_digest((username or "").encode(), settings.ADMIN_USERNAME.encode())
    pass_ok = hmac.compare_digest((password or "").encode(), settings.ADMIN_PASSWORD.encode())
    return user_ok and pass_ok


def rate_limited(client: str) -> bool:
    """True when `client` exceeded the allowed number of failed logins in the window."""
    now = time.time()
    with _attempts_lock:
        attempts = _attempts[client]
        while attempts and attempts[0] < now - _WINDOW_SECONDS:
            attempts.popleft()
        return len(attempts) >= _MAX_ATTEMPTS


def record_failure(client: str) -> None:
    with _attempts_lock:
        _attempts[client].append(time.time())


def reset_failures(client: str) -> None:
    with _attempts_lock:
        _attempts.pop(client, None)


def _api_key_from(request: Request) -> Optional[str]:
    key = request.headers.get("x-api-key")
    if key:
        return key
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def current_user(request: Request) -> Optional[str]:
    """Username of the caller, 'anonymous' when auth is disabled, None when not logged in."""
    if not settings.auth_enabled:
        return "anonymous"
    key = _api_key_from(request)
    if key and settings.ADMIN_API_KEY and hmac.compare_digest(key.encode(), settings.ADMIN_API_KEY.encode()):
        return "api-key"
    return verify_session_token(request.cookies.get(COOKIE_NAME))


def require_admin(request: Request) -> str:
    """Dependency for the management API."""
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_ui_login(request: Request) -> str:
    """Dependency for dashboard pages: redirects to the login page instead of a 401."""
    user = current_user(request)
    if user is None:
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise LoginRequired(target)
    return user
