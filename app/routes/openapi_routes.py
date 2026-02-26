from fastapi import APIRouter, Request
from fastapi import FastAPI
from app.services.openapi_extraction_service import OpenAPIExtractionService

router = APIRouter()

@router.get("/extract-openapi")
def extract_openapi(request: Request):
    app=request.app
    raw_spec, normalized = OpenAPIExtractionService.run_extraction(app)
    return{"message": "OpenAPI extracted","raw":raw_spec, "normalized": normalized}