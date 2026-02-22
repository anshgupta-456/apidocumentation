from fastapi import APIRouter, Request
from fastapi import FastAPI
from app.services.openapi_extraction_service import OpenAPIExtractionnService

router = APIRouter()

@router.get("/extract-openapi")
def extract_openapi(request: Request):
    app=request.app
    result = OpenAPIExtractionnService.run_extraction(app)
    return{"message": "OpenAPI extracted", "normalized": result}