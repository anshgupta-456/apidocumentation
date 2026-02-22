from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from app.database.session import SessionLocal
from app.database.models import DriftEvents, OpenAPISpec

router = APIRouter(prefix="/ui", tags=["UI"])

templates = Jinja2Templates(directory="app/ui/templates")

@router.get("/")
def dashboard(request: Request):
    db = SessionLocal()

    total_drifts = db.query(DriftEvents).count()
    total_specs = db.query(OpenAPISpec).count()

    latest_spec = (
        db.query(OpenAPISpec)
        .order_by(OpenAPISpec.extracted_at.desc())
        .first()
    )
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "total_drifts": total_drifts,
            "total_specs": total_specs,
            "latest_spec": latest_spec,
        }
    )

@router.get("/drifts")
def drift_events(request: Request):
    db = SessionLocal()
    events = (
        db.query(DriftEvents)
        .order_by(DriftEvents.detected_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "drift.html",
        {
            "request": request,
            "events": events
        }
    )

@router.get("/drift/{drift_id}")
def drift_detail(request: Request, drift_id: str):
    db = SessionLocal()
    event = db.query(DriftEvents).filter(DriftEvents.id == drift_id).first()

    return templates.TemplateResponse(
        "drift_detail.html",
        {"request": request, "event": event}
    )
@router.get("/openapi")
def openapi_versions(request:Request):
    db = SessionLocal()
    specs = (
        db.query(OpenAPISpec)
        .order_by(OpenAPISpec.extracted_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "openapi_list.html",
        {"request": request, "specs": specs}
    )
