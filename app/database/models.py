import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.database.base import Base

# JSONB on PostgreSQL, plain JSON everywhere else (e.g. SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _maybe_json(value):
    """Patches / explanations are stored as text; return parsed JSON when possible."""
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


class ApiLog(Base):
    __tablename__ = "api_logs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint = Column(Text, nullable=False, index=True)  # concrete path, e.g. /api/users/3
    route_path = Column(Text, nullable=True, index=True)  # route template, e.g. /api/users/{user_id}
    method = Column(Text, nullable=False)
    request_json = Column(JSONType)
    response_json = Column(JSONType)
    status_code = Column(Integer)
    latency_ms = Column(Integer)
    api_version = Column(Text)
    client_ip = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True)

    def to_dict(self, include_bodies: bool = True) -> dict:
        data = {
            "id": str(self.id),
            "endpoint": self.endpoint,
            "route_path": self.route_path,
            "method": self.method,
            "status_code": self.status_code,
            "latency_ms": self.latency_ms,
            "api_version": self.api_version,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "created_at": _iso(self.created_at),
        }
        if include_bodies:
            data["request_json"] = self.request_json
            data["response_json"] = self.response_json
        return data


class InferredSchema(Base):
    __tablename__ = "inferred_schemas"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint = Column(Text, nullable=False)
    method = Column(Text, nullable=False)
    location = Column(String(20), nullable=True, server_default="response")
    schema_json = Column(JSONType, nullable=False)
    sample_size = Column(Integer, nullable=False)
    schema_hash = Column(Text, nullable=False)
    # Column name kept as "computed_At" for compatibility with existing databases.
    computed_at = Column("computed_At", DateTime(timezone=True), default=utcnow, server_default=func.now())


class OpenAPISpec(Base):
    __tablename__ = "openapi_specs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    version_hash = Column(Text, nullable=False)
    spec_json = Column(JSONType, nullable=False)
    normalized_paths = Column(JSONType, nullable=False)
    extracted_at = Column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    @property
    def endpoint_count(self) -> int:
        paths = (self.spec_json or {}).get("paths", {})
        return sum(
            1
            for methods in paths.values()
            for m in methods
            if m.lower() in {"get", "post", "put", "patch", "delete", "head", "options"}
        )

    def to_dict(self, include_spec: bool = False) -> dict:
        data = {
            "id": str(self.id),
            "version_hash": self.version_hash,
            "short_hash": (self.version_hash or "")[:12],
            "endpoint_count": self.endpoint_count,
            "extracted_at": _iso(self.extracted_at),
        }
        if include_spec:
            data["spec_json"] = self.spec_json
            data["normalized_paths"] = self.normalized_paths
        return data


DRIFT_STATUSES = ("open", "acknowledged", "resolved", "ignored")
SEVERITIES = ("low", "medium", "high")


class DriftEvents(Base):
    __tablename__ = "drift_events"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint = Column(Text, nullable=False, index=True)
    method = Column(Text, nullable=False)
    severity = Column(Text, nullable=False)
    drift_detail = Column(JSONType, nullable=False)
    ai_explanation = Column(Text, nullable=False)
    openapi_patch = Column(Text, nullable=True)
    backend_patch = Column(Text, nullable=True)
    detected_at = Column(DateTime(timezone=True), default=utcnow)

    # v2 fields (added automatically to existing databases on startup)
    status = Column(String(20), nullable=True, server_default="open")
    issue_count = Column(Integer, nullable=True)
    fingerprint = Column(Text, nullable=True, index=True)
    occurrences = Column(Integer, nullable=True, server_default="1")
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    ai_provider = Column(String(30), nullable=True)
    notes = Column(Text, nullable=True)

    def to_dict(self, full: bool = True) -> dict:
        from app.services.drift_detection_service import normalize_drift_detail

        detail = normalize_drift_detail(self.drift_detail)
        data = {
            "id": str(self.id),
            "endpoint": self.endpoint,
            "method": self.method,
            "severity": self.severity,
            "status": self.status or "open",
            "issue_count": self.issue_count if self.issue_count is not None else len(detail["issues"]),
            "occurrences": self.occurrences or 1,
            "ai_provider": self.ai_provider,
            "detected_at": _iso(self.detected_at),
            "last_seen_at": _iso(self.last_seen_at or self.detected_at),
            "resolved_at": _iso(self.resolved_at),
            "notes": self.notes,
        }
        if full:
            data.update(
                {
                    "drift_detail": detail,
                    "ai_explanation": _maybe_json(self.ai_explanation),
                    "openapi_patch": _maybe_json(self.openapi_patch),
                    "backend_patch": self.backend_patch,
                }
            )
        return data
