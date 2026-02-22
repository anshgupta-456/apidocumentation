
from fastapi import APIRouter, Request
from app.services.schema_inference_service import SchemaInferenceService
from app.services.openapi_extraction_service import OpenAPIExtractionService
from app.services.drift_detection_service import SchemaDriftService
from app.database.session import SessionLocal
from app.database.models import DriftEvents
router = APIRouter()

@router.get("/detect-drift/{endpoint:path}")
def detect_drift(request: Request, endpoint: str):
    app = request.app

    # Normalize endpoint path
    endpoint = endpoint.strip()
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    endpoint = endpoint.rstrip("/")   # remove trailing slash

    # Normalize method
    method = "POST"
    method = method.upper()

    # 1️⃣ Get runtime schema
    runtime = SchemaInferenceService.run_inference(endpoint, method)

    # 2️⃣ Get OpenAPI extracted schema
    spec, normalized = OpenAPIExtractionService.extracted_paths(app)

    print("🔍 Normalized paths:", list(normalized.keys()))
    print("🔍 Endpoint requested:", endpoint)

    # 3️⃣ Validate endpoint existence
    if endpoint not in normalized:
        return {
            "error": f"Endpoint {endpoint} not documented in OpenAPI",
            "available_endpoints": list(normalized.keys())
        }

    # Normalize method keys in OpenAPI (POST vs post)
    openapi_methods = {m.upper(): v for m, v in normalized[endpoint].items()}

    # 4️⃣ Validate method existence
    if method.upper() not in openapi_methods:
        return {
            "error": f"Method {method} not documented for endpoint {endpoint}",
            "available_methods": list(openapi_methods.keys())
        }

    expected_schema = openapi_methods[method]

    # 5️⃣ Compare schemas
    drift_report = SchemaDriftService.compare(expected_schema, runtime)

    # 6️⃣ Save drift event to DB
    SchemaDriftService.save_drift(endpoint, method, drift_report)

    return {
        "message": "Drift detection complete",
        "endpoint": endpoint,
        "method": method,
        "drift_report": drift_report
    }
@router.get("/drift-events")
def drift_events():
    db = SessionLocal()
    events = db.query(DriftEvents).order_by(DriftEvents.detected_at.desc()).all()
    db.close()
    return events
@router.get("/drift-events/{id}")
def drift_event_detail(id:str):
    db = SessionLocal()
    event = db.query(DriftEvents).filter(DriftEvents.id == id).first()
    db.close()

    if not event:
        return{"error": "Drift event not found"}
    return event