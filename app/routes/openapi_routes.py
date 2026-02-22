from fastapi import APIRouter
from fastapi import FastAPI
from app.services.openapi_extraction_service import OpenAPIExtractionnService

router = APIRouter()

@router.get("/extract-openapi")
def extract_openapi(app: FastAPI):
    result = OpenAPIExtractionnService.run.extraction(app)
    return{"message": "OpenAPI extracted", "normalized": result}