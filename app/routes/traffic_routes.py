import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import ApiLog
from app.database.session import check_db, get_db
from app.services.alert_service import AlertService
from app.services.job_service import JobState, cleanup_logs, run_scan
from app.services.playground_service import PlaygroundService
from app.services.traffic_service import RANGES, TrafficService

# Public router (no auth): used by load balancers / uptime monitors.
public_router = APIRouter(tags=["System"])
router = APIRouter(tags=["Traffic & system"])


@public_router.get("/health")
def health():
    db_ok = check_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": settings.VERSION,
        "database": "ok" if db_ok else "unreachable",
        "database_backend": settings.database_backend,
        "ai": {
            "provider": "groq" if settings.ai_available else "rule-based",
            "model": settings.AI_MODEL if settings.ai_available else None,
        },
        "auth_enabled": settings.auth_enabled,
    }


def config_summary() -> dict:
    """Non-secret view of the running configuration (shown on the settings page)."""
    return {
        "version": settings.VERSION,
        "database_backend": settings.database_backend,
        "auth_enabled": settings.auth_enabled,
        "admin_username": settings.ADMIN_USERNAME if settings.auth_enabled else None,
        "api_key_configured": bool(settings.ADMIN_API_KEY),
        "secret_key_configured": bool(settings.SECRET_KEY),
        "ai_provider": "groq" if settings.ai_available else "rule-based",
        "ai_model": settings.AI_MODEL,
        "ai_key_configured": bool(settings.GROQ_API_KEY),
        "monitored_prefixes": list(settings.LOG_INCLUDE_PREFIXES),
        "redacted_fields": list(settings.REDACT_FIELDS),
        "log_max_body_bytes": settings.LOG_MAX_BODY_BYTES,
        "log_retention_days": settings.LOG_RETENTION_DAYS,
        "inference_sample_limit": settings.INFERENCE_SAMPLE_LIMIT,
        "auto_scan_interval_minutes": settings.AUTO_SCAN_INTERVAL_MINUTES,
        "alerts_configured": AlertService.enabled(),
        "alert_min_severity": settings.ALERT_MIN_SEVERITY,
        "public_base_url": settings.PUBLIC_BASE_URL or None,
        "demo_enabled": settings.DEMO_ENABLED,
        "cors_origins": list(settings.CORS_ORIGINS),
    }


@router.get("/system/config")
def system_config():
    return {"config": config_summary(), "jobs": JobState.snapshot(), "last_alert": AlertService.last_status}


@router.post("/system/cleanup")
def run_cleanup(days: Optional[int] = Query(None, ge=1, le=3650)):
    """Delete captured traffic older than `days` (default: LOG_RETENTION_DAYS)."""
    if days is None and settings.LOG_RETENTION_DAYS <= 0:
        return {"message": "Retention is disabled (LOG_RETENTION_DAYS=0); pass ?days=N", "deleted": 0}
    deleted = cleanup_logs(days)
    return {"message": f"Deleted {deleted} old log entries", "deleted": deleted}


@router.post("/system/scan")
def run_background_scan(request: Request):
    """Run the scheduled scan job now (same as POST /drift/scan, but recorded as the last auto-scan)."""
    return run_scan(request.app)


@router.post("/alerts/test")
def test_alert():
    result = AlertService.send_test()
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Webhook call failed")
    return {"message": "Test alert delivered", **result}


@router.get("/stats")
def stats(request: Request, range: str = Query("24h", enum=list(RANGES)), db: Session = Depends(get_db)):
    """Aggregated numbers that power the dashboard."""
    return TrafficService.stats(request.app, db, range)


@router.get("/endpoints")
def endpoints(request: Request, all: bool = False, db: Session = Depends(get_db)):
    """Documented vs observed endpoints with traffic, error-rate, latency and drift status."""
    return TrafficService.endpoint_overview(request.app, db, monitored_only=not all)


@router.get("/endpoints/detail")
def endpoint_detail(
    request: Request,
    path: str,
    method: str,
    range: str = Query("24h", enum=list(RANGES)),
    db: Session = Depends(get_db),
):
    """Everything about one operation: traffic, latency, status codes, schema comparison, drift history."""
    detail = TrafficService.endpoint_detail(request.app, db, path, method, range)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"{method.upper()} {path} is neither documented nor observed")
    return detail


@router.get("/playground/operations")
def playground_operations(request: Request, all: bool = False):
    """Request templates (path/query params, example body) for every documented operation."""
    return PlaygroundService.operations(request.app, monitored_only=not all)


@router.get("/api-logs")
def list_logs(
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    status: Optional[str] = Query(None, description="'success', 'error' or an exact status code"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    total, items = TrafficService.list_logs(db, endpoint, method, status, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": [i.to_dict() for i in items]}


@router.get("/api-logs/{log_id}")
def log_detail(log_id: uuid.UUID, db: Session = Depends(get_db)):
    log = db.get(ApiLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return log.to_dict()


@router.delete("/api-logs")
def clear_logs(endpoint: Optional[str] = None, method: Optional[str] = None, db: Session = Depends(get_db)):
    """Delete captured traffic (optionally only for one endpoint/method), e.g. after fixing drift."""
    deleted = TrafficService.clear_logs(db, endpoint, method)
    return {"message": f"Deleted {deleted} log entries", "deleted": deleted}
