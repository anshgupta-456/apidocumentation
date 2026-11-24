import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import DriftEvents
from app.database.session import get_db
from app.services.drift_detection_service import normalize_endpoint
from app.services.openapi_extraction_service import OpenAPIExtractionService
from app.services.openapi_patch_service import OpenAPIPatchService

router = APIRouter(prefix="/patch", tags=["Patches"])


def _find_event(db: Session, event_id: Optional[str], endpoint: Optional[str], method: Optional[str]) -> DriftEvents:
    if event_id:
        try:
            event = db.get(DriftEvents, uuid.UUID(str(event_id)))
        except ValueError:
            event = None
    elif endpoint and method:
        event = (
            db.query(DriftEvents)
            .filter(DriftEvents.endpoint == normalize_endpoint(endpoint), DriftEvents.method == method.upper())
            .order_by(DriftEvents.detected_at.desc())
            .first()
        )
    else:
        raise HTTPException(status_code=400, detail="Provide either event_id or endpoint + method")
    if not event:
        raise HTTPException(status_code=404, detail="No drift event / patch found")
    return event


@router.get("/generated-spec")
def download_generated_spec():
    """Download the spec produced by the last applied patch."""
    if not os.path.exists(settings.GENERATED_SPEC_PATH):
        raise HTTPException(status_code=404, detail="No patch has been applied yet")
    return FileResponse(
        settings.GENERATED_SPEC_PATH, media_type="application/json", filename="openapi.generated.json"
    )


@router.get("/{event_id}")
def get_patch(event_id: str, db: Session = Depends(get_db)):
    event = _find_event(db, event_id, None, None)
    data = event.to_dict()
    return {
        "event_id": data["id"],
        "endpoint": event.endpoint,
        "method": event.method,
        "openapi_patch": data["openapi_patch"],
        "backend_patch": data["backend_patch"],
    }


@router.post("/apply")
def apply_patches(
    request: Request,
    event_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Merge a drift event's OpenAPI patch into the live spec and write openapi.generated.json.

    The running code is never modified; the backend patch is returned for review.
    """
    event = _find_event(db, event_id, endpoint, method)
    data = event.to_dict()
    base = OpenAPIExtractionService.live_spec(request.app)
    try:
        result = OpenAPIPatchService.apply_patch(base, data["openapi_patch"])
        openapi_result = {k: v for k, v in result.items() if k != "spec"}
    except ValueError as exc:
        openapi_result = {"message": str(exc)}

    return {
        "message": "Patch processed",
        "event_id": data["id"],
        "endpoint": event.endpoint,
        "method": event.method,
        "results": {
            "openapi": openapi_result,
            "backend": data["backend_patch"] or "No backend patch available",
        },
    }
