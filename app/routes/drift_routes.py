import csv
import io
import json
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database.models import DriftEvents, utcnow
from app.database.session import get_db
from app.schemas.api_schemas import BulkDriftUpdate, DriftStatusUpdate, ScanRequest
from app.services.drift_detection_service import SchemaDriftService

router = APIRouter(tags=["Drift detection"])

SeverityFilter = Optional[Literal["low", "medium", "high"]]
StatusFilter = Optional[Literal["open", "acknowledged", "resolved", "ignored", "active"]]


@router.get("/detect-drift/{endpoint:path}")
def detect_drift(
    request: Request,
    endpoint: str,
    method: Optional[str] = Query(None, description="HTTP method. Omit to analyse every method with traffic."),
    save: bool = Query(True, description="Store a drift event when drift is found."),
    use_ai: bool = Query(True, description="Use the AI explainer when configured."),
    db: Session = Depends(get_db),
):
    """Compare the documented contract of one endpoint with its observed traffic."""
    results = SchemaDriftService.detect(request.app, db, endpoint, method, save=save, use_ai=use_ai)
    if not results:
        raise HTTPException(status_code=404, detail=f"No documented operations or traffic for '{endpoint}'.")
    return {
        "message": "Drift detection complete",
        "endpoint": results[0]["endpoint"],
        "drift_found": any(r["has_drift"] for r in results),
        "results": results,
    }


@router.post("/drift/scan")
def scan_all(request: Request, options: ScanRequest = ScanRequest(), db: Session = Depends(get_db)):
    """Run drift detection for every endpoint that has captured traffic."""
    return SchemaDriftService.scan_all(request.app, db, save=options.save, use_ai=options.use_ai)


def _filtered_events(
    db: Session,
    severity: Optional[str],
    status: Optional[str],
    endpoint: Optional[str],
    method: Optional[str],
):
    query = db.query(DriftEvents)
    if severity:
        query = query.filter(DriftEvents.severity == severity)
    if status == "active":
        query = query.filter(DriftEvents.status.in_(("open", "acknowledged")) | DriftEvents.status.is_(None))
    elif status == "open":
        query = query.filter((DriftEvents.status == "open") | DriftEvents.status.is_(None))
    elif status:
        query = query.filter(DriftEvents.status == status)
    if endpoint:
        query = query.filter(DriftEvents.endpoint.like(f"%{endpoint}%"))
    if method:
        query = query.filter(DriftEvents.method == method.upper())
    return query.order_by(DriftEvents.detected_at.desc())


@router.get("/drift-events")
def list_drift_events(
    severity: SeverityFilter = None,
    status: StatusFilter = Query(None, description="'active' = open + acknowledged"),
    endpoint: Optional[str] = Query(None, description="Substring match on the endpoint path"),
    method: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = _filtered_events(db, severity, status, endpoint, method)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [e.to_dict(full=False) for e in items]}


@router.get("/drift-events/export")
def export_drift_events(
    format: Literal["csv", "json"] = "csv",
    severity: SeverityFilter = None,
    status: StatusFilter = Query(None, description="'active' = open + acknowledged"),
    endpoint: Optional[str] = None,
    db: Session = Depends(get_db),
):
    events = [e.to_dict(full=format == "json") for e in _filtered_events(db, severity, status, endpoint, None).all()]
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    if format == "json":
        payload = json.dumps(events, indent=2, default=str)
        return StreamingResponse(
            iter([payload]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="drift-events-{stamp}.json"'},
        )

    columns = [
        "id", "endpoint", "method", "severity", "status", "issue_count",
        "occurrences", "detected_at", "last_seen_at", "resolved_at", "ai_provider", "notes",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(events)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="drift-events-{stamp}.csv"'},
    )


@router.post("/drift-events/bulk")
def bulk_update_drift_events(payload: BulkDriftUpdate, db: Session = Depends(get_db)):
    """Change the status of (or delete) many drift events at once."""
    if not payload.delete and not payload.status:
        raise HTTPException(status_code=422, detail="Provide a status or delete=true")
    count = SchemaDriftService.bulk_update(db, payload.ids, payload.status, payload.delete)
    action = "deleted" if payload.delete else f"marked {payload.status}"
    return {"message": f"{count} event(s) {action}", "updated": count}


def _get_event(db: Session, event_id: uuid.UUID) -> DriftEvents:
    event = db.get(DriftEvents, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Drift event not found")
    return event


@router.get("/drift-events/{event_id}")
def drift_event_detail(event_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_event(db, event_id).to_dict()


@router.patch("/drift-events/{event_id}")
def update_drift_event(event_id: uuid.UUID, payload: DriftStatusUpdate, db: Session = Depends(get_db)):
    """Move a drift event through its lifecycle (open → acknowledged → resolved / ignored)."""
    event = _get_event(db, event_id)
    if payload.status:
        event.status = payload.status
        event.resolved_at = utcnow() if payload.status in ("resolved", "ignored") else None
    if payload.notes is not None:
        event.notes = payload.notes
    db.commit()
    return event.to_dict(full=False)


@router.delete("/drift-events/{event_id}", status_code=204)
def delete_drift_event(event_id: uuid.UUID, db: Session = Depends(get_db)):
    db.delete(_get_event(db, event_id))
    db.commit()
