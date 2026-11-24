"""Pure ASGI middleware that records API traffic for schema inference.

Unlike a BaseHTTPMiddleware it never buffers or rebuilds the response: chunks are
streamed straight through while a copy (up to LOG_MAX_BODY_BYTES) is kept for logging.
Persisting the log runs in a worker thread and can never break the actual request.
"""
import json
import logging
import time

from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database.models import ApiLog
from app.database.session import SessionLocal

logger = logging.getLogger(__name__)


def should_log(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in settings.LOG_INCLUDE_PREFIXES)


def _parse_json(raw: bytes):
    if not raw:
        return None
    try:
        return redact(json.loads(raw))
    except (ValueError, UnicodeDecodeError):
        return None


def _is_sensitive(key: str) -> bool:
    key = key.lower()
    return key in settings.REDACT_FIELDS or any(
        marker in key for marker in ("password", "secret", "token") if marker in settings.REDACT_FIELDS
    )


def redact(value):
    """Mask sensitive values while keeping their JSON type, so schema inference still works."""
    if isinstance(value, dict):
        masked = {}
        for key, child in value.items():
            if _is_sensitive(str(key)) and not isinstance(child, (dict, list)):
                if isinstance(child, bool) or child is None:
                    masked[key] = child
                elif isinstance(child, (int, float)):
                    masked[key] = 0
                else:
                    masked[key] = "[REDACTED]"
            else:
                masked[key] = redact(child)
        return masked
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class LoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not should_log(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        limit = settings.LOG_MAX_BODY_BYTES
        start = time.perf_counter()
        request_body = bytearray()
        response_body = bytearray()
        state = {"status": 500, "is_json": False, "overflow": False}

        async def receive_wrapper():
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                if len(request_body) + len(chunk) <= limit:
                    request_body.extend(chunk)
            return message

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                for key, value in message.get("headers", []):
                    if key.lower() == b"content-type":
                        state["is_json"] = b"json" in value.lower()
            elif message["type"] == "http.response.body" and state["is_json"]:
                chunk = message.get("body", b"")
                if len(response_body) + len(chunk) <= limit:
                    response_body.extend(chunk)
                else:
                    state["overflow"] = True
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        finally:
            route = scope.get("route")
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            client = scope.get("client")
            entry = {
                "endpoint": scope.get("path", ""),
                "route_path": getattr(route, "path", None),
                "method": scope.get("method", "GET").upper(),
                "request_json": _parse_json(bytes(request_body)),
                "response_json": None if state["overflow"] else _parse_json(bytes(response_body)),
                "status_code": state["status"],
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "api_version": headers.get("x-api-version", "v1"),
                "client_ip": client[0] if client else None,
                "user_agent": headers.get("user-agent"),
            }
            await run_in_threadpool(self._save, entry)

    @staticmethod
    def _save(entry: dict) -> None:
        db = SessionLocal()
        try:
            db.add(ApiLog(**entry))
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist API log for %s %s", entry["method"], entry["endpoint"])
        finally:
            db.close()
