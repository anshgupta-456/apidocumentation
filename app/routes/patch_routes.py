
from fastapi import APIRouter, HTTPException
from app.services.ai_patch_service import AIPatchService
from app.services.openapi_patch_service import OpenAPIPatchService

router = APIRouter(prefix="/patch", tags=["Patches"])

@router.post("/apply")
def apply_patches(endpoint: str, method: str):
    patches = AIPatchService.get_saved_patch_for(endpoint, method)

    if not patches:
        raise HTTPException(
            status_code=404,
            detail=f"No patches found for {endpoint} {method}"
        )

    openapi_patch = patches.get("openapi_patch")
    backend_patch = patches.get("backend_patch")

    result = {}

    if isinstance(openapi_patch, dict):
        result["openapi"] = OpenAPIPatchService.apply_patch(openapi_patch)
    else:
        result["openapi"] = "No OpenAPI patch available"

    result["backend"] = backend_patch or "No backend patch available"

    return {
        "message": "Patch processed",
        "endpoint": endpoint,
        "method": method,
        "results": result
    }