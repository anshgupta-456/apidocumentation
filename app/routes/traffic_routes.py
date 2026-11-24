import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import ApiLog
from app.database.session import check_db, get_db
from app.services.traffic_service import TrafficService

router = APIRouter(tags=["Traffic & system"])


@router.get("/health")
def health():
    db_ok = check_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": settings.VERSION,
        "database": "ok" if db_ok else "unreachable",
        "database_backend": settings.DATABASE_URL.split(":", 1)[0],
        "ai": {
            "provider": "groq" if settings.ai_available else "rule-based",
            "model": settings.AI_MODEL if settings.ai_available else None,
        },
        "monitored_prefixes": list(settings.LOG_INCLUDE_PREFIXES),
    }


@router.get("/stats")
def stats(request: Request, db: Session = Depends(get_db)):
    """Aggregated numbers that power the dashboard."""
    return TrafficService.stats(request.app, db)


@router.get("/endpoints")
def endpoints(request: Request, all: bool = False, db: Session = Depends(get_db)):
    """Documented vs observed endpoints with traffic, error-rate, latency and drift status."""
    return TrafficService.endpoint_overview(request.app, db, monitored_only=not all)


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
