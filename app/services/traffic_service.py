"""Traffic analytics: endpoint coverage, time series, request statistics and log browsing."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import ApiLog, DriftEvents, OpenAPISpec, utcnow
from app.database.session import engine
from app.services.drift_detection_service import ACTIVE_STATUSES, SEVERITY_RANK, SchemaDriftService
from app.services.openapi_extraction_service import OpenAPIExtractionService
from app.services.schema_inference_service import SchemaInferenceService
from app.utils.schema_utils import match_template

RANGES = {
    "24h": {"delta": timedelta(hours=24), "bucket": "hour", "count": 24, "label": "Last 24 hours"},
    "7d": {"delta": timedelta(days=7), "bucket": "day", "count": 7, "label": "Last 7 days"},
    "30d": {"delta": timedelta(days=30), "bucket": "day", "count": 30, "label": "Last 30 days"},
}
HEALTH_WEIGHTS = {"high": 15, "medium": 6, "low": 2}


def _is_monitored(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in settings.LOG_INCLUDE_PREFIXES)


def _percentile(values, pct):
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, max(0, int(round(pct / 100 * (len(values) - 1)))))
    return values[index]


def _bucket_expr(bucket: str):
    column = ApiLog.created_at
    if engine.dialect.name == "postgresql":
        fmt = "YYYY-MM-DD HH24:00:00" if bucket == "hour" else "YYYY-MM-DD"
        return func.to_char(func.date_trunc(bucket, func.timezone("UTC", column)), fmt)
    return func.strftime("%Y-%m-%d %H:00:00" if bucket == "hour" else "%Y-%m-%d", column)


def _route_filter(path: str, method: str):
    return and_(
        ApiLog.method == method.upper(),
        or_(ApiLog.route_path == path, and_(ApiLog.route_path.is_(None), ApiLog.endpoint == path)),
    )


def resolve_range(range_key: Optional[str]) -> str:
    return range_key if range_key in RANGES else "24h"


class TrafficService:
    # ------------------------------------------------------------------ building blocks
    @staticmethod
    def timeseries(db: Session, range_key: str, extra_filter=None) -> list:
        cfg = RANGES[range_key]
        now = utcnow()
        if cfg["bucket"] == "hour":
            end = now.replace(minute=0, second=0, microsecond=0)
            starts = [end - timedelta(hours=i) for i in range(cfg["count"] - 1, -1, -1)]
            key = lambda dt: dt.strftime("%Y-%m-%d %H:00:00")  # noqa: E731
        else:
            end = now.replace(hour=0, minute=0, second=0, microsecond=0)
            starts = [end - timedelta(days=i) for i in range(cfg["count"] - 1, -1, -1)]
            key = lambda dt: dt.strftime("%Y-%m-%d")  # noqa: E731

        bucket = _bucket_expr(cfg["bucket"])
        query = db.query(
            bucket,
            func.count(ApiLog.id),
            func.sum(case((ApiLog.status_code >= 400, 1), else_=0)),
            func.avg(ApiLog.latency_ms),
        ).filter(ApiLog.created_at >= starts[0])
        if extra_filter is not None:
            query = query.filter(extra_filter)
        rows = {str(b): (c, e, a) for b, c, e, a in query.group_by(bucket).all()}

        series = []
        for start in starts:
            count, errors, avg = rows.get(key(start), (0, 0, None))
            series.append(
                {
                    "t": start.replace(tzinfo=timezone.utc).isoformat(),
                    "requests": int(count or 0),
                    "errors": int(errors or 0),
                    "avg_latency_ms": round(float(avg), 1) if avg is not None else None,
                }
            )
        return series

    @staticmethod
    def traffic_summary(db: Session, since: Optional[datetime], extra_filter=None) -> dict:
        def scoped(query):
            if since is not None:
                query = query.filter(ApiLog.created_at >= since)
            if extra_filter is not None:
                query = query.filter(extra_filter)
            return query

        total, errors, avg = scoped(
            db.query(func.count(ApiLog.id), func.sum(case((ApiLog.status_code >= 400, 1), else_=0)), func.avg(ApiLog.latency_ms))
        ).one()
        total, errors = int(total or 0), int(errors or 0)
        latencies = [
            r[0]
            for r in scoped(db.query(ApiLog.latency_ms)).order_by(ApiLog.created_at.desc()).limit(5000).all()
            if r[0] is not None
        ]
        codes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
        for code, count in scoped(db.query(ApiLog.status_code, func.count(ApiLog.id))).group_by(ApiLog.status_code).all():
            if code is not None and 200 <= code < 600:
                codes[f"{code // 100}xx"] = codes.get(f"{code // 100}xx", 0) + count
        return {
            "total": total,
            "errors": errors,
            "error_rate": round(errors / total * 100, 1) if total else 0.0,
            "avg_latency_ms": round(float(avg), 1) if avg is not None else None,
            "p95_latency_ms": _percentile(latencies, 95),
            "p50_latency_ms": _percentile(latencies, 50),
            "status_codes": codes,
        }

    @staticmethod
    def health_score(open_by_severity: dict, coverage_percent: float, has_traffic: bool) -> dict:
        penalty = sum(HEALTH_WEIGHTS.get(s, 0) * n for s, n in open_by_severity.items())
        score = max(0, 100 - penalty)
        if has_traffic and coverage_percent < 50:
            score = max(0, score - 5)
        if score >= 90:
            label, tone = "Healthy", "good"
        elif score >= 70:
            label, tone = "Minor drift", "warning"
        elif score >= 40:
            label, tone = "Needs attention", "serious"
        else:
            label, tone = "Critical", "critical"
        return {"score": score, "label": label, "tone": tone}

    # ------------------------------------------------------------------ endpoint overview
    @staticmethod
    def endpoint_overview(app: FastAPI, db: Session, monitored_only: bool = True) -> list:
        _, normalized = OpenAPIExtractionService.extracted_paths(app)
        templates = list(normalized.keys())

        rows = (
            db.query(
                func.coalesce(ApiLog.route_path, ApiLog.endpoint),
                ApiLog.method,
                func.count(ApiLog.id),
                func.avg(ApiLog.latency_ms),
                func.sum(case((ApiLog.status_code >= 400, 1), else_=0)),
                func.max(ApiLog.created_at),
            )
            .group_by(func.coalesce(ApiLog.route_path, ApiLog.endpoint), ApiLog.method)
            .all()
        )

        stats = {}
        for path, method, count, avg_latency, errors, last_seen in rows:
            route = match_template(path, templates) or path
            key = (route, method.upper())
            entry = stats.setdefault(key, {"requests": 0, "latency_total": 0.0, "errors": 0, "last_seen": None})
            entry["requests"] += count
            entry["latency_total"] += float(avg_latency or 0) * count
            entry["errors"] += int(errors or 0)
            if last_seen is not None and (entry["last_seen"] is None or str(last_seen) > str(entry["last_seen"])):
                entry["last_seen"] = last_seen

        drift_rows = (
            db.query(DriftEvents.endpoint, DriftEvents.method, DriftEvents.severity)
            .filter(DriftEvents.status.in_(ACTIVE_STATUSES) | DriftEvents.status.is_(None))
            .all()
        )
        drift = {}
        for endpoint, method, severity in drift_rows:
            entry = drift.setdefault((endpoint, method.upper()), {"open": 0, "severity": None})
            entry["open"] += 1
            if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(entry["severity"], 0):
                entry["severity"] = severity

        keys = set(stats)
        for path, methods in normalized.items():
            for method in methods:
                keys.add((path, method))

        overview = []
        for route, method in sorted(keys):
            if monitored_only and not _is_monitored(route):
                continue
            s = stats.get((route, method), {})
            op = normalized.get(route, {}).get(method)
            requests = s.get("requests", 0)
            d = drift.get((route, method), {})
            last_seen = s.get("last_seen")
            overview.append(
                {
                    "endpoint": route,
                    "method": method,
                    "summary": (op or {}).get("summary"),
                    "documented": op is not None,
                    "requests": requests,
                    "error_rate": round(s.get("errors", 0) / requests * 100, 1) if requests else 0.0,
                    "avg_latency_ms": round(s.get("latency_total", 0) / requests, 1) if requests else None,
                    "last_seen": last_seen.isoformat() if hasattr(last_seen, "isoformat") else last_seen,
                    "open_drifts": d.get("open", 0),
                    "drift_severity": d.get("severity"),
                }
            )
        return overview

    # ------------------------------------------------------------------ dashboard
    @staticmethod
    def stats(app: FastAPI, db: Session, range_key: str = "24h") -> dict:
        range_key = resolve_range(range_key)
        since = utcnow() - RANGES[range_key]["delta"]

        in_range = TrafficService.traffic_summary(db, since)
        all_time_total = db.query(func.count(ApiLog.id)).scalar() or 0

        severity_rows = db.query(DriftEvents.severity, func.count(DriftEvents.id)).group_by(DriftEvents.severity).all()
        by_status = {"open": 0, "acknowledged": 0, "resolved": 0, "ignored": 0}
        for status, count in db.query(DriftEvents.status, func.count(DriftEvents.id)).group_by(DriftEvents.status).all():
            by_status[status or "open"] = by_status.get(status or "open", 0) + count

        open_by_severity = {"high": 0, "medium": 0, "low": 0}
        for severity, count in (
            db.query(DriftEvents.severity, func.count(DriftEvents.id))
            .filter(DriftEvents.status.in_(ACTIVE_STATUSES) | DriftEvents.status.is_(None))
            .group_by(DriftEvents.severity)
            .all()
        ):
            open_by_severity[severity] = open_by_severity.get(severity, 0) + count

        overview = TrafficService.endpoint_overview(app, db, monitored_only=True)
        documented = [e for e in overview if e["documented"]]
        covered = [e for e in documented if e["requests"] > 0]
        coverage = round(len(covered) / len(documented) * 100, 1) if documented else 0.0
        top = sorted((e for e in overview if e["requests"]), key=lambda e: e["requests"], reverse=True)[:6]

        recent_events = db.query(DriftEvents).order_by(DriftEvents.detected_at.desc()).limit(6).all()
        latest_spec = db.query(OpenAPISpec).order_by(OpenAPISpec.extracted_at.desc()).first()
        open_total = by_status.get("open", 0) + by_status.get("acknowledged", 0)

        return {
            "range": range_key,
            "range_label": RANGES[range_key]["label"],
            "bucket": RANGES[range_key]["bucket"],
            "health": TrafficService.health_score(open_by_severity, coverage, all_time_total > 0),
            "requests": {**in_range, "all_time": all_time_total},
            "endpoints": {
                "monitored": len(overview),
                "documented": len(documented),
                "covered": len(covered),
                "undocumented": sum(1 for e in overview if not e["documented"]),
                "coverage_percent": coverage,
            },
            "drift": {
                "total": sum(c for _, c in severity_rows),
                "open": open_total,
                "by_severity": {s: c for s, c in severity_rows},
                "open_by_severity": open_by_severity,
                "by_status": by_status,
            },
            "specs": {
                "total": db.query(func.count(OpenAPISpec.id)).scalar() or 0,
                "latest": latest_spec.to_dict() if latest_spec else None,
            },
            "traffic": TrafficService.timeseries(db, range_key),
            "top_endpoints": top,
            "recent_events": [e.to_dict(full=False) for e in recent_events],
        }

    # ------------------------------------------------------------------ endpoint detail
    @staticmethod
    def endpoint_detail(app: FastAPI, db: Session, path: str, method: str, range_key: str = "24h") -> Optional[dict]:
        range_key = resolve_range(range_key)
        method = method.upper()
        _, normalized = OpenAPIExtractionService.extracted_paths(app)
        templates = list(normalized.keys())
        path = match_template(path, templates) or path
        operation = normalized.get(path, {}).get(method)

        route_filter = _route_filter(path, method)
        has_logs = db.query(ApiLog.id).filter(route_filter).first() is not None
        if operation is None and not has_logs:
            return None

        since = utcnow() - RANGES[range_key]["delta"]
        summary_all = TrafficService.traffic_summary(db, None, route_filter)
        summary_range = TrafficService.traffic_summary(db, since, route_filter)
        last_seen = db.query(func.max(ApiLog.created_at)).filter(route_filter).scalar()

        inference = SchemaInferenceService.infer(db, path, method, templates, persist=False)
        schemas = {}
        for location in ("response", "request"):
            expected = (operation or {}).get(location, {})
            runtime = inference[location]
            schemas[location] = {
                "documented": bool((operation or {}).get(f"{location}_documented")),
                "samples": inference[f"{location}_samples"],
                "rows": SchemaDriftService.field_rows(
                    expected, runtime, location, (operation or {}).get(f"{location}_free_form", False)
                ),
            }

        events = (
            db.query(DriftEvents)
            .filter(DriftEvents.endpoint == path, DriftEvents.method == method)
            .order_by(DriftEvents.detected_at.desc())
            .limit(20)
            .all()
        )
        recent_logs = db.query(ApiLog).filter(route_filter).order_by(ApiLog.created_at.desc()).limit(12).all()

        return {
            "endpoint": path,
            "method": method,
            "summary": (operation or {}).get("summary"),
            "operation_id": (operation or {}).get("operation_id"),
            "tags": (operation or {}).get("tags", []),
            "documented": operation is not None,
            "monitored": _is_monitored(path),
            "response_status": (operation or {}).get("response_status"),
            "range": range_key,
            "range_label": RANGES[range_key]["label"],
            "bucket": RANGES[range_key]["bucket"],
            "all_time": summary_all,
            "in_range": summary_range,
            "last_seen": last_seen.isoformat() if hasattr(last_seen, "isoformat") else last_seen,
            "traffic": TrafficService.timeseries(db, range_key, route_filter),
            "schemas": schemas,
            "events": [e.to_dict(full=False) for e in events],
            "open_events": sum(1 for e in events if (e.status or "open") in ACTIVE_STATUSES),
            "recent_logs": [log.to_dict() for log in recent_logs],
        }

    # ------------------------------------------------------------------ logs
    @staticmethod
    def list_logs(
        db: Session,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ):
        query = db.query(ApiLog)
        if endpoint:
            like = f"%{endpoint}%"
            query = query.filter(ApiLog.endpoint.like(like) | ApiLog.route_path.like(like))
        if method:
            query = query.filter(ApiLog.method == method.upper())
        if status == "success":
            query = query.filter(ApiLog.status_code < 400)
        elif status == "error":
            query = query.filter(ApiLog.status_code >= 400)
        elif status and status.isdigit():
            query = query.filter(ApiLog.status_code == int(status))
        total = query.count()
        items = query.order_by(ApiLog.created_at.desc()).offset(offset).limit(limit).all()
        return total, items

    @staticmethod
    def clear_logs(db: Session, endpoint: Optional[str] = None, method: Optional[str] = None) -> int:
        query = db.query(ApiLog)
        if endpoint:
            query = query.filter((ApiLog.route_path == endpoint) | (ApiLog.endpoint == endpoint))
        if method:
            query = query.filter(ApiLog.method == method.upper())
        deleted = query.delete(synchronize_session=False)
        db.commit()
        return deleted
