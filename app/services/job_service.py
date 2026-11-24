"""Background jobs: periodic drift scans and log retention."""
import asyncio
import logging
from datetime import timedelta
from typing import Optional

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database.models import ApiLog, utcnow
from app.database.session import SessionLocal

logger = logging.getLogger(__name__)

TICK_SECONDS = 60
CLEANUP_EVERY = timedelta(hours=6)


class JobState:
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


async def scheduler(app: FastAPI) -> None:
    """Runs forever (cancelled on shutdown). Failures are logged and never stop the loop."""
    while True:
        try:
            now = utcnow()
            if settings.LOG_RETENTION_DAYS > 0 and (
                JobState.last_cleanup_at is None or now - JobState.last_cleanup_at >= CLEANUP_EVERY
            ):
                await run_in_threadpool(cleanup_logs)
            interval = settings.AUTO_SCAN_INTERVAL_MINUTES
            if interval > 0:
                if JobState.last_scan_at is None:
                    JobState.last_scan_at = now  # first scan one interval after startup
                elif now - JobState.last_scan_at >= timedelta(minutes=interval):
                    await run_in_threadpool(run_scan, app)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Background job failed")
        await asyncio.sleep(TICK_SECONDS)
