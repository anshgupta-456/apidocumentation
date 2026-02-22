# from fastapi import APIRouter, Request
# from app.services.schema_inference_service import SchemaInferenceService
# from app.services.openapi_extraction_service import OpenAPIExtractionService
# from app.services.drift_detection_service import SchemaDriftService

# router = APIRouter()

# @router.get("/detect-drift/{endpoint:path}")
# def detect_drift(request: Request, endpoint: str):
    

#     app = request.app
#     if not endpoint.startswith("/"):
#         endpoint = "/" + endpoint
#     method = "POST"
#     # GEtting runtime schema
#     runtime = SchemaInferenceService.run_inference(endpoint,method)

#     #Getting openapi spec
#     spec, normalized = OpenAPIExtractionService.extracted_paths(app)

#     if endpoint not in normalized:
#         return {"error": "Endpoint not documented in OpenAPI"}
#     if method not in normalized:
#         return {"error": "Method not documented"}
#     expected_schema = normalized[endpoint][method]
#     #comparing schemas
#     drift = SchemaDriftService.compare(expected_schema,runtime)

#     #save drift event to db
#     SchemaDriftService.save_drift(endpoint, drift)

#     return{
#         "message":"Drift detection complete",
#         "endpoint":endpoint,
#         "drift_report": drift
#     }
from fastapi import APIRouter, Request
from app.services.schema_inference_service import SchemaInferenceService
from app.services.openapi_extraction_service import OpenAPIExtractionService
from app.services.drift_detection_service import SchemaDriftService

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