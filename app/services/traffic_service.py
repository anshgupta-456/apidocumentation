"""Traffic analytics: endpoint coverage, request statistics and log browsing."""
from datetime import timedelta
from typing import Optional

from fastapi import FastAPI
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import ApiLog, DriftEvents, OpenAPISpec, utcnow
from app.services.drift_detection_service import ACTIVE_STATUSES, SEVERITY_RANK
from app.services.openapi_extraction_service import OpenAPIExtractionService
from app.utils.schema_utils import match_template


def _is_monitored(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in settings.LOG_INCLUDE_PREFIXES)


def _percentile(values, pct):
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, max(0, int(round(pct / 100 * (len(values) - 1)))))
    return values[index]


class TrafficService:
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

    @staticmethod
    def stats(app: FastAPI, db: Session) -> dict:
        now = utcnow()
        day_ago = now - timedelta(hours=24)
        week_ago = now - timedelta(days=6)

        total_requests = db.query(func.count(ApiLog.id)).scalar() or 0
        requests_24h = db.query(func.count(ApiLog.id)).filter(ApiLog.created_at >= day_ago).scalar() or 0
        errors = db.query(func.count(ApiLog.id)).filter(ApiLog.status_code >= 400).scalar() or 0
        avg_latency = db.query(func.avg(ApiLog.latency_ms)).scalar()
        recent_latencies = [
            row[0]
            for row in db.query(ApiLog.latency_ms).order_by(ApiLog.created_at.desc()).limit(1000).all()
            if row[0] is not None
        ]

        severity_rows = (
            db.query(DriftEvents.severity, func.count(DriftEvents.id)).group_by(DriftEvents.severity).all()
        )
        status_rows = db.query(DriftEvents.status, func.count(DriftEvents.id)).group_by(DriftEvents.status).all()
        by_status = {"open": 0, "acknowledged": 0, "resolved": 0, "ignored": 0}
        for status, count in status_rows:
            by_status[status or "open"] = by_status.get(status or "open", 0) + count

        open_by_severity = {"high": 0, "medium": 0, "low": 0}
        for severity, count in (
            db.query(DriftEvents.severity, func.count(DriftEvents.id))
            .filter(DriftEvents.status.in_(ACTIVE_STATUSES) | DriftEvents.status.is_(None))
            .group_by(DriftEvents.severity)
            .all()
        ):
            open_by_severity[severity] = open_by_severity.get(severity, 0) + count

        day_rows = (
            db.query(
                func.date(ApiLog.created_at),
                func.count(ApiLog.id),
                func.sum(case((ApiLog.status_code >= 400, 1), else_=0)),
            )
            .filter(ApiLog.created_at >= week_ago.replace(hour=0, minute=0, second=0, microsecond=0))
            .group_by(func.date(ApiLog.created_at))
            .all()
        )
        per_day = {str(day): (count, int(errs or 0)) for day, count, errs in day_rows}
        traffic = []
        for offset in range(6, -1, -1):
            day = (now - timedelta(days=offset)).date()
            count, errs = per_day.get(str(day), (0, 0))
            traffic.append({"date": str(day), "label": day.strftime("%a"), "requests": count, "errors": errs})

        overview = TrafficService.endpoint_overview(app, db, monitored_only=True)
        documented = [e for e in overview if e["documented"]]
        covered = [e for e in documented if e["requests"] > 0]
        top = sorted((e for e in overview if e["requests"]), key=lambda e: e["requests"], reverse=True)[:5]

        recent_events = db.query(DriftEvents).order_by(DriftEvents.detected_at.desc()).limit(5).all()
        latest_spec = db.query(OpenAPISpec).order_by(OpenAPISpec.extracted_at.desc()).first()

        return {
            "requests": {
                "total": total_requests,
                "last_24h": requests_24h,
                "errors": errors,
                "error_rate": round(errors / total_requests * 100, 1) if total_requests else 0.0,
                "avg_latency_ms": round(float(avg_latency), 1) if avg_latency is not None else None,
                "p95_latency_ms": _percentile(recent_latencies, 95),
            },
            "endpoints": {
                "monitored": len(overview),
                "documented": len(documented),
                "covered": len(covered),
                "undocumented": sum(1 for e in overview if not e["documented"]),
                "coverage_percent": round(len(covered) / len(documented) * 100, 1) if documented else 0.0,
            },
            "drift": {
                "total": sum(c for _, c in severity_rows),
                "open": by_status.get("open", 0) + by_status.get("acknowledged", 0),
                "by_severity": {s: c for s, c in severity_rows},
                "open_by_severity": open_by_severity,
                "by_status": by_status,
            },
            "specs": {
                "total": db.query(func.count(OpenAPISpec.id)).scalar() or 0,
                "latest": latest_spec.to_dict() if latest_spec else None,
            },
            "traffic": traffic,
            "top_endpoints": top,
            "recent_events": [e.to_dict(full=False) for e in recent_events],
        }

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
