import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database.models import OpenAPISpec
from app.database.session import get_db
from app.services.openapi_extraction_service import OpenAPIExtractionService
from app.services.spec_diff_service import SpecDiffService

router = APIRouter(tags=["OpenAPI versions"])


@router.get("/extract-openapi")
def extract_openapi(request: Request, include_spec: bool = True, db: Session = Depends(get_db)):
    """Snapshot the live OpenAPI spec. A new version is stored only when the spec changed."""
    result = OpenAPIExtractionService.run_extraction(request.app, db)
    body = {
        "message": "New OpenAPI version stored" if result["created"] else "No changes since the last extraction",
        "changed": result["created"],
        "version": result["record"].to_dict(),
        "diff": result["diff"],
    }
    if include_spec:
        body["raw"] = result["spec"]
        body["normalized"] = result["normalized"]
    return body


@router.get("/openapi-specs")
def list_specs(db: Session = Depends(get_db)):
    specs = db.query(OpenAPISpec).order_by(OpenAPISpec.extracted_at.desc()).all()
    return [s.to_dict() for s in specs]


def _resolve_spec(db: Session, spec_id: Optional[str]) -> OpenAPISpec:
    if spec_id in (None, "", "latest"):
        spec = OpenAPIExtractionService.latest(db)
    else:
        try:
            spec = db.get(OpenAPISpec, uuid.UUID(str(spec_id)))
        except ValueError:
            spec = None
    if not spec:
        raise HTTPException(status_code=404, detail=f"OpenAPI version '{spec_id}' not found")
    return spec


@router.get("/openapi-specs/diff")
def diff_specs(
    request: Request,
    base: Optional[str] = None,
    target: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Diff two stored versions. `target` defaults to the live spec, `base` to the latest stored one."""
    base_spec = _resolve_spec(db, base)
    if target in (None, "", "live"):
        target_json, target_info = OpenAPIExtractionService.live_spec(request.app), {"id": "live"}
    else:
        target_spec = _resolve_spec(db, target)
        target_json, target_info = target_spec.spec_json, target_spec.to_dict()
    return {
        "base": base_spec.to_dict(),
        "target": target_info,
        "diff": SpecDiffService.diff(base_spec.spec_json, target_json),
    }


@router.get("/openapi-specs/{spec_id}")
def spec_detail(spec_id: str, db: Session = Depends(get_db)):
    return _resolve_spec(db, spec_id).to_dict(include_spec=True)


@router.get("/openapi-specs/{spec_id}/download")
def download_spec(spec_id: str, db: Session = Depends(get_db)):
    spec = _resolve_spec(db, spec_id)
    return Response(
        content=json.dumps(spec.spec_json, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="openapi-{spec.version_hash[:12]}.json"'},
    )
