import json
import math
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.database.models import DriftEvents, OpenAPISpec
from app.database.session import get_db
from app.routes.drift_routes import _filtered_events
from app.services.openapi_extraction_service import OpenAPIExtractionService
from app.services.spec_diff_service import SpecDiffService
from app.services.traffic_service import TrafficService

router = APIRouter(prefix="/ui", tags=["UI"], include_in_schema=False)
templates = Jinja2Templates(directory=str(BASE_DIR / "ui" / "templates"))
PAGE_SIZE = 25


# ---------------------------------------------------------------------- template helpers
def _to_datetime(value) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def fmt_datetime(value) -> str:
    dt = _to_datetime(value)
    return dt.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC") if dt else "—"


def time_ago(value) -> str:
    dt = _to_datetime(value)
    if not dt:
        return "never"
    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    if seconds < 45:
        return "just now"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return f"{seconds}s ago"


def pretty_json(value) -> str:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


templates.env.filters["dt"] = fmt_datetime
templates.env.filters["ago"] = time_ago
templates.env.filters["pretty"] = pretty_json
templates.env.globals["settings"] = settings


def render(request: Request, name: str, context: dict, status_code: int = 200):
    context.setdefault("active", "")
    context["ai_provider"] = "groq" if settings.ai_available else "rule-based"
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def pager(request: Request, total: int, page: int) -> dict:
    pages = max(1, math.ceil(total / PAGE_SIZE))
    params = {k: v for k, v in request.query_params.items() if k != "page" and v}

    def link(p):
        return "?" + urlencode({**params, "page": p})

    return {
        "page": page,
        "pages": pages,
        "total": total,
        "prev": link(page - 1) if page > 1 else None,
        "next": link(page + 1) if page < pages else None,
        "start": (page - 1) * PAGE_SIZE + 1 if total else 0,
        "end": min(page * PAGE_SIZE, total),
    }


def not_found(request: Request, message: str):
    return render(request, "error.html", {"message": message}, status_code=404)


# ---------------------------------------------------------------------- pages
@router.get("")
@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    stats = TrafficService.stats(request.app, db)
    max_traffic = max([d["requests"] for d in stats["traffic"]] + [1])
    return render(request, "dashboard.html", {"active": "dashboard", "stats": stats, "max_traffic": max_traffic})


@router.get("/endpoints")
def endpoints_page(request: Request, all: bool = False, db: Session = Depends(get_db)):
    overview = TrafficService.endpoint_overview(request.app, db, monitored_only=not all)
    return render(
        request,
        "endpoints.html",
        {
            "active": "endpoints",
            "endpoints": overview,
            "show_all": all,
            "documented": sum(1 for e in overview if e["documented"]),
            "covered": sum(1 for e in overview if e["documented"] and e["requests"]),
            "undocumented": sum(1 for e in overview if not e["documented"]),
        },
    )


@router.get("/drifts")
def drift_events(
    request: Request,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    page: int = 1,
    db: Session = Depends(get_db),
):
    page = max(1, page)
    query = _filtered_events(db, severity or None, status or None, endpoint or None, method or None)
    total = query.count()
    events = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    filters = {"severity": severity or "", "status": status or "", "endpoint": endpoint or "", "method": method or ""}
    export_query = urlencode({k: v for k, v in filters.items() if v and k != "method"})
    status_links = [
        {
            "label": label,
            "active": filters["status"] == value,
            "href": "?" + urlencode({k: v for k, v in {**filters, "status": value}.items() if v}),
        }
        for value, label in (("", "All"), ("active", "Active"), ("resolved", "Resolved"), ("ignored", "Ignored"))
    ]
    return render(
        request,
        "drifts.html",
        {
            "active": "drifts",
            "events": [e.to_dict(full=False) for e in events],
            "filters": filters,
            "pager": pager(request, total, page),
            "export_query": export_query,
            "status_links": status_links,
        },
    )


@router.get("/drift/{drift_id}")
def drift_detail(request: Request, drift_id: str, db: Session = Depends(get_db)):
    try:
        event = db.get(DriftEvents, uuid.UUID(drift_id))
    except ValueError:
        event = None
    if not event:
        return not_found(request, "This drift event does not exist (it may have been deleted).")
    data = event.to_dict()
    explanation = data["ai_explanation"]
    return render(
        request,
        "drift_detail.html",
        {
            "active": "drifts",
            "event": data,
            "explanation": explanation if isinstance(explanation, dict) else None,
            "raw_explanation": explanation if not isinstance(explanation, dict) else None,
        },
    )


@router.get("/openapi")
def openapi_versions(request: Request, db: Session = Depends(get_db)):
    specs = db.query(OpenAPISpec).order_by(OpenAPISpec.extracted_at.desc()).all()
    live_hash = OpenAPIExtractionService.compute_hash(OpenAPIExtractionService.live_spec(request.app))
    return render(
        request,
        "openapi_list.html",
        {"active": "openapi", "specs": [s.to_dict() for s in specs], "live_hash": live_hash},
    )


@router.get("/openapi/diff")
def openapi_diff(request: Request, base: Optional[str] = None, target: Optional[str] = None, db: Session = Depends(get_db)):
    def load(spec_id):
        if spec_id in (None, "", "latest"):
            return OpenAPIExtractionService.latest(db)
        try:
            return db.get(OpenAPISpec, uuid.UUID(spec_id))
        except ValueError:
            return None

    base_spec = load(base)
    if not base_spec:
        return not_found(request, "Extract at least one OpenAPI version before comparing.")
    if target in (None, "", "live"):
        target_json, target_info = OpenAPIExtractionService.live_spec(request.app), None
    else:
        target_spec = load(target)
        if not target_spec:
            return not_found(request, "Target OpenAPI version not found.")
        target_json, target_info = target_spec.spec_json, target_spec.to_dict()

    return render(
        request,
        "openapi_diff.html",
        {
            "active": "openapi",
            "base": base_spec.to_dict(),
            "target": target_info,
            "diff": SpecDiffService.diff(base_spec.spec_json, target_json),
        },
    )


@router.get("/openapi/{spec_id}")
def openapi_detail(request: Request, spec_id: str, db: Session = Depends(get_db)):
    try:
        spec = db.get(OpenAPISpec, uuid.UUID(spec_id))
    except ValueError:
        spec = None
    if not spec:
        return not_found(request, "OpenAPI version not found.")
    normalized = OpenAPIExtractionService.normalize_spec(spec.spec_json)
    operations = [
        {"endpoint": path, "method": method, **op}
        for path, methods in sorted(normalized.items())
        for method, op in sorted(methods.items())
    ]
    return render(
        request,
        "openapi_detail.html",
        {"active": "openapi", "spec": spec.to_dict(), "operations": operations},
    )


@router.get("/logs")
def logs_page(
    request: Request,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    db: Session = Depends(get_db),
):
    page = max(1, page)
    total, items = TrafficService.list_logs(
        db, endpoint or None, method or None, status or None, PAGE_SIZE, (page - 1) * PAGE_SIZE
    )
    return render(
        request,
        "logs.html",
        {
            "active": "logs",
            "logs": [i.to_dict() for i in items],
            "filters": {"endpoint": endpoint or "", "method": method or "", "status": status or ""},
            "pager": pager(request, total, page),
        },
    )
