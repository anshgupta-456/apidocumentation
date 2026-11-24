"""Background jobs: keep-alive pings, periodic drift scans and log retention."""
import asyncio
import logging
from datetime import timedelta
from typing import Optional

import httpx
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database.models import ApiLog, utcnow
from app.database.session import SessionLocal

logger = logging.getLogger(__name__)

TICK_SECONDS = 60
CLEANUP_EVERY = timedelta(hours=6)


class JobState:
    started_at = None
    last_ping_at = None
    last_ping_result: Optional[dict] = None
    last_scan_at = None
    last_scan_result: Optional[dict] = None
    last_cleanup_at = None
    last_cleanup_deleted: Optional[int] = None

    @classmethod
    def snapshot(cls) -> dict:
        def iso(value):
            return value.isoformat() if value else None

        next_scan = None
        if settings.AUTO_SCAN_INTERVAL_MINUTES > 0:
            base = cls.last_scan_at or utcnow()
            next_scan = iso(base + timedelta(minutes=settings.AUTO_SCAN_INTERVAL_MINUTES))
        return {
            "auto_scan_interval_minutes": settings.AUTO_SCAN_INTERVAL_MINUTES,
            "last_scan_at": iso(cls.last_scan_at),
            "last_scan_result": cls.last_scan_result,
            "next_scan_at": next_scan,
            "log_retention_days": settings.LOG_RETENTION_DAYS,
            "last_cleanup_at": iso(cls.last_cleanup_at),
            "last_cleanup_deleted": cls.last_cleanup_deleted,
            "keep_alive_enabled": settings.keep_alive_enabled,
            "keep_alive_url": settings.KEEP_ALIVE_URL or None,
            "keep_alive_interval_minutes": settings.KEEP_ALIVE_INTERVAL_MINUTES,
            "last_ping_at": iso(cls.last_ping_at),
            "last_ping_result": cls.last_ping_result,
        }


def cleanup_logs(days: Optional[int] = None) -> int:
    """Delete captured traffic older than `days` (defaults to LOG_RETENTION_DAYS)."""
    days = settings.LOG_RETENTION_DAYS if days is None else days
    if days <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=days)
    db = SessionLocal()
    try:
        deleted = db.query(ApiLog).filter(ApiLog.created_at < cutoff).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    JobState.last_cleanup_at = utcnow()
    JobState.last_cleanup_deleted = deleted
    if deleted:
        logger.info("Retention: deleted %s log entries older than %s days", deleted, days)
    return deleted


def keep_alive_ping() -> dict:
    """Request our own public URL so the hosting platform sees inbound traffic.

    Hits /health/live, which never touches the database, so a serverless Postgres
    (e.g. Neon) can still scale to zero between real requests.
    """
    url = f"{settings.KEEP_ALIVE_URL}/health/live"
    started = utcnow()
    try:
        response = httpx.get(url, timeout=30, headers={"User-Agent": "api-contract-validator-keep-alive"})
        result = {"ok": response.status_code < 400, "status_code": response.status_code}
    except httpx.HTTPError as exc:
        result = {"ok": False, "error": str(exc)[:200]}
    result["latency_ms"] = int((utcnow() - started).total_seconds() * 1000)
    JobState.last_ping_at = utcnow()
    JobState.last_ping_result = result
    if not result["ok"]:
        logger.warning("Keep-alive ping to %s failed: %s", url, result)
    return result


def keep_alive_due(now) -> bool:
    if not settings.keep_alive_enabled:
        return False
    last = JobState.last_ping_at or JobState.started_at or now
    return now - last >= timedelta(minutes=settings.KEEP_ALIVE_INTERVAL_MINUTES)


def run_scan(app: FastAPI) -> dict:
    from app.services.drift_detection_service import SchemaDriftService

    db = SessionLocal()
    try:
        result = SchemaDriftService.scan_all(app, db, save=True, use_ai=True)
    finally:
        db.close()
    summary = {k: v for k, v in result.items() if k != "results"}
    JobState.last_scan_at = utcnow()
    JobState.last_scan_result = summary
    logger.info("Auto-scan: %s", summary)
    return summary


async def _run_safely(name: str, func, *args) -> None:
    try:
        await run_in_threadpool(func, *args)
    except Exception:  # one failing job must never stop the others
        logger.exception("Background job %s failed", name)


async def scheduler(app: FastAPI) -> None:
    """Runs forever (cancelled on shutdown). Failures are logged and never stop the loop."""
    JobState.started_at = utcnow()
    if settings.keep_alive_enabled:
        logger.info(
            "Keep-alive: pinging %s/health/live every %s min",
            settings.KEEP_ALIVE_URL,
            settings.KEEP_ALIVE_INTERVAL_MINUTES,
        )
        if settings.KEEP_ALIVE_INTERVAL_MINUTES >= 15:
            logger.warning("KEEP_ALIVE_INTERVAL_MINUTES >= 15 - Render free instances sleep after 15 idle minutes")
    while True:
        now = utcnow()
        if keep_alive_due(now):
            await _run_safely("keep-alive", keep_alive_ping)
        if settings.LOG_RETENTION_DAYS > 0 and (
            JobState.last_cleanup_at is None or now - JobState.last_cleanup_at >= CLEANUP_EVERY
        ):
            await _run_safely("retention", cleanup_logs)
        interval = settings.AUTO_SCAN_INTERVAL_MINUTES
        if interval > 0:
            if JobState.last_scan_at is None:
                JobState.last_scan_at = now  # first scan one interval after startup
            elif now - JobState.last_scan_at >= timedelta(minutes=interval):
                await _run_safely("auto-scan", run_scan, app)
        await asyncio.sleep(TICK_SECONDS)
