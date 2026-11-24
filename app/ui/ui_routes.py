import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import current_user, require_ui_login
from app.config import BASE_DIR, settings
from app.database.models import DriftEvents, OpenAPISpec
from app.database.session import get_db
from app.routes.drift_routes import _filtered_events
from app.routes.traffic_routes import config_summary
from app.services.alert_service import AlertService
from app.services.drift_detection_service import SchemaDriftService
from app.services.job_service import JobState
from app.services.openapi_extraction_service import OpenAPIExtractionService
from app.services.playground_service import PlaygroundService
from app.services.spec_diff_service import SpecDiffService
from app.services.traffic_service import RANGES, TrafficService, resolve_range

public_router = APIRouter(prefix="/ui", include_in_schema=False)
router = APIRouter(prefix="/ui", tags=["UI"], include_in_schema=False, dependencies=[Depends(require_ui_login)])
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
    if seconds < 0:
        seconds = abs(seconds)
        for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
            if seconds >= size:
                return f"in {seconds // size}{unit}"
        return "in a moment"
    if seconds < 45:
        return "just now"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return f"{seconds}s ago"


def pretty_json(value) -> str:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


def compact_number(value) -> str:
    if value is None:
        return "—"
    value = float(value)
    for suffix, size in (("M", 1_000_000), ("K", 10_000)):
        if abs(value) >= size:
            divisor = size if suffix == "M" else 1000
            return f"{value / divisor:.1f}".rstrip("0").rstrip(".") + suffix
    return f"{int(value):,}" if value == int(value) else f"{value:,.1f}"


templates.env.filters["dt"] = fmt_datetime
templates.env.filters["ago"] = time_ago
templates.env.filters["pretty"] = pretty_json
templates.env.filters["compact"] = compact_number
templates.env.filters["tojson_attr"] = lambda v: json.dumps(v, default=str)
templates.env.globals["settings"] = settings
templates.env.globals["RANGES"] = RANGES


def _asset_version() -> str:
    """Content hash of the static assets, so browsers fetch fresh CSS/JS after every deploy."""
    digest = hashlib.sha256()
    for path in sorted((BASE_DIR / "ui" / "static").rglob("*")):
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


templates.env.globals["asset_v"] = _asset_version()


def render(request: Request, name: str, context: dict, status_code: int = 200):
    context.setdefault("active", "")
    context["ai_provider"] = "groq" if settings.ai_available else "rule-based"
    context["user"] = current_user(request)
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


# ---------------------------------------------------------------------- public pages
@public_router.get("/login")
def login_page(request: Request, next: str = "/ui"):
    if not next.startswith("/") or next.startswith("//"):
        next = "/ui"
    if not settings.auth_enabled or current_user(request):
        return RedirectResponse(next, status_code=303)
    return templates.TemplateResponse(request, "login.html", {"next": next, "settings": settings})


# ---------------------------------------------------------------------- pages
@router.get("")
@router.get("/")
def dashboard(request: Request, range: Optional[str] = None, db: Session = Depends(get_db)):
    range_key = resolve_range(range)
    stats = TrafficService.stats(request.app, db, range_key)
    return render(request, "dashboard.html", {"active": "dashboard", "stats": stats, "range": range_key})


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
            "with_drift": sum(1 for e in overview if e["open_drifts"]),
        },
    )


@router.get("/endpoint")
def endpoint_page(
    request: Request, path: str, method: str = "GET", range: Optional[str] = None, db: Session = Depends(get_db)
):
    detail = TrafficService.endpoint_detail(request.app, db, path, method, resolve_range(range))
    if detail is None:
        return not_found(request, f"{method.upper()} {path} is neither documented nor observed.")
    return render(request, "endpoint.html", {"active": "endpoints", "d": detail})


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
    detail = data["drift_detail"]
    explanation = data["ai_explanation"]
    schema_rows = {}
    for location in ("response", "request"):
        expected = (detail.get("expected_schema") or {}).get(location) or {}
        runtime = (detail.get("runtime_schema") or {}).get(location) or {}
        schema_rows[location] = SchemaDriftService.field_rows(expected, runtime, location) if (expected or runtime) else []
    return render(
        request,
        "drift_detail.html",
        {
            "active": "drifts",
            "event": data,
            "schema_rows": schema_rows,
            "explanation": explanation if isinstance(explanation, dict) else None,
            "raw_explanation": explanation if not isinstance(explanation, dict) else None,
        },
    )


@router.get("/playground")
def playground_page(request: Request, all: bool = False):
    operations = PlaygroundService.operations(request.app, monitored_only=not all)
    return render(request, "playground.html", {"active": "playground", "operations": operations, "show_all": all})


@router.get("/settings")
def settings_page(request: Request):
    return render(
        request,
        "settings.html",
        {
            "active": "settings",
            "config": config_summary(),
            "jobs": JobState.snapshot(),
            "last_alert": AlertService.last_status,
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
