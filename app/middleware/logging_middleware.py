import time
import json
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.database.session import SessionLocal
from app.database.models import ApiLog


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):

        start_time = time.time()

        # Read request body
        try:
            request_body = await request.json()
        except:
            request_body = None

        response = await call_next(request)

        # Capture response body
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        response = response.__class__(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type
        )

        try:
            parsed_response = json.loads(response_body)
        except:
            parsed_response = None

        latency = int((time.time() - start_time) * 1000)

        # Save to DB
        db = SessionLocal()
        try:
            log_entry = ApiLog(
                endpoint=request.url.path,
                method=request.method,
                request_json=request_body,
                response_json=parsed_response,
                status_code=response.status_code,
                latency_ms=latency,
                api_version="v1"
            )
            db.add(log_entry)
            db.commit()
        finally:
            db.close()

        return response
