# # from fastapi import APIRouter, HTTPException
# # from app.services.openapi_patch_service import OpenAPIPatchService
# # from app.services.backend_patch_service import BackendPatchService
# # from app.services.ai_patch_service import AIPatchService

# # router = APIRouter(prefix="/patch", tags=["Patches"])

# # @router.post("/apply")
# # def apply_patches(endpoint: str, method: str):
# #     patches = AIPatchService.get_saved_patch_for(endpoint, method)
# #     if patches is None:
# #         raise HTTPException(status_code=404, detail="No patches found for this endpoint and method")
# #     openapi_patch = patches.get("openapi_patch")
# #     backend_patch = patches.get("backend_patch")

# #     results = {}

# #     if openapi_patch:
# #         results["openapi"] = OpenAPIPatchService.apply_patch(openapi_patch)
# #     else:
# #         results["openapi"] = "No OpenAPI patch available"
# #     if backend_patch:
# #         results["backend"] = BackendPatchService.apply_patch(backend_patch)
# #     else:
# #         results["backend"] = "No backend patch available"
# #     return{
# #         "message": "Patches applied",
# #         "results": results
# #     }

# from fastapi import APIRouter, HTTPException
# from app.services.ai_patch_service import AIPatchService

# router = APIRouter(prefix="/patch", tags=["Patches"])


# @router.post("/apply")
# def apply_patches(endpoint: str, method: str):
#     """
#     Retrieve saved patches from patches.json for the given endpoint & method.
#     """
#     patches = AIPatchService.get_saved_patch_for(endpoint, method)

#     if not patches:
#         raise HTTPException(
#             status_code=404,
#             detail=f"No patch found for {endpoint} {method}"
#         )

#     return {
#         "message": "Patch retrieved successfully",
#         "endpoint": endpoint,
#         "method": method,
#         "patch": patches
#     }
from fastapi import APIRouter, HTTPException
from app.services.ai_patch_service import AIPatchService

router = APIRouter(prefix="/patch", tags=["Patches"])


@router.post("/apply")
def apply_patches(endpoint: str, method: str):
    """
    Return the saved patches from patches.json for a specific endpoint & method.
    """
    patches = AIPatchService.get_saved_patch_for(endpoint, method)

    if patches is None:
        raise HTTPException(
            status_code=404,
            detail=f"No patch found for {endpoint} {method}"
        )

    return {
        "message": "Patch retrieved successfully",
        "endpoint": endpoint,
        "method": method,
        "patch": patches
    }