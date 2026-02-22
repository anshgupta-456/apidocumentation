from fastapi import APIRouter
from app.database.models import DriftEvents
from app.database.session import SessionLocal

router = APIRouter()
@router.get("/drift-events")
def list_drift_events():
    db = SessionLocal()
    events = db.query(DriftEvents).order_by(DriftEvents.detected_at.desc()).all()
    db.close()
    return events