from fastapi import APIRouter, Request
from app.services.schema_inference_service import SchemaInferenceService
from app.services.openapi_extraction_service import OpenAPIExtractionService
from app.services.drift_detection_service import SchemaDriftService

router = APIRouter()

@router.get("/defect-drift/{endpoint}")
def defect_drift(request: Request, endpoint: str):
    method = "Post"

    app = request.app
    # GEtting runtime schema
    runtime = SchemaInferenceService.run_inference(endpoint,method)

    #Getting openapi spec
    spec, normalized = OpenAPIExtractionService.extracted_paths(app)

    if endpoint not in normalized:
        return {"error": "Endpoint not documented in OpenAPI"}
    if method not in normalized:
        return {"error": "Method not documented"}
    expected_schema = normalized[endpoint][method]
    #comparing schemas
    drift = SchemaDriftService.compare(expected_schema,runtime)

    #save drift event to db
    SchemaDriftService.save_drift(endpoint, drift)

    return{
        "message":"Drift detection complete",
        "endpoint":endpoint,
        "drift_report": drift
    }