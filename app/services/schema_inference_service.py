"""Infers the *real* request/response schema of an endpoint from captured traffic."""
import hashlib
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import ApiLog, InferredSchema
from app.utils.schema_utils import join_path, match_template, parent_of


class SchemaInferenceService:
    @staticmethod
    def infer_type(value: Any) -> str:
        """Infer the JSON data type of a value."""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "unknown"

    @staticmethod
    def _walk(value: Any, path: str, stats: Dict, containers: Dict) -> None:
        """Recursively record statistics for every field below `path`."""
        if isinstance(value, dict):
            containers[path] = containers.get(path, 0) + 1
            for key, child in value.items():
                field = join_path(path, str(key))
                entry = stats.setdefault(
                    field, {"count": 0, "types": {}, "null_count": 0, "example": None, "item_types": set()}
                )
                entry["count"] += 1
                child_type = SchemaInferenceService.infer_type(child)
                entry["types"][child_type] = entry["types"].get(child_type, 0) + 1
                if child is None:
                    entry["null_count"] += 1
                elif entry["example"] is None and not isinstance(child, (dict, list)):
                    entry["example"] = child if not isinstance(child, str) else child[:80]
                if isinstance(child, list):
                    for item in child:
                        if not isinstance(item, (dict, list)):
                            entry["item_types"].add(SchemaInferenceService.infer_type(item))
                SchemaInferenceService._walk(child, field, stats, containers)
        elif isinstance(value, list):
            item_path = f"{path}[]"
            for item in value:
                if isinstance(item, dict):
                    SchemaInferenceService._walk(item, item_path, stats, containers)

    @staticmethod
    def build_schema_from_bodies(bodies: List[Any]) -> Dict:
        """Aggregate many JSON bodies into a flattened runtime schema.

        `presence_percent` is relative to how often the *parent* object appeared, so a
        nested field that is always present when its parent is present is "required".
        """
        stats: Dict = {}
        containers: Dict = {}
        for body in bodies:
            if isinstance(body, (dict, list)):
                SchemaInferenceService._walk(body, "", stats, containers)

        schema: Dict = {}
        for field, s in stats.items():
            parent_total = containers.get(parent_of(field), 0) or s["count"]
            presence = round(s["count"] / parent_total * 100, 2)
            schema[field] = {
                "types": sorted(t for t in s["types"] if t != "null"),
                "presence_percent": presence,
                "nullable": s["null_count"] > 0,
                "required": presence >= 100.0,
                "count": s["count"],
                "example": s["example"],
            }
            item_types = sorted(t for t in s["item_types"] if t != "null")
            if item_types:
                schema[field]["item_types"] = item_types
        return schema

    @staticmethod
    def build_schema(logs: List[ApiLog]) -> Dict:
        """Backward compatible helper: runtime schema of the response bodies of `logs`."""
        return SchemaInferenceService.build_schema_from_bodies([log.response_json for log in logs])

    @staticmethod
    def compute_hash(schema_json: Dict) -> str:
        encoded = json.dumps(schema_json, sort_keys=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def fetch_logs(db: Session, route: str, method: str, templates: Optional[list] = None) -> List[ApiLog]:
        """Most recent logs for a route template (also matches legacy logs without route_path)."""
        limit = settings.INFERENCE_SAMPLE_LIMIT
        logs = (
            db.query(ApiLog)
            .filter(ApiLog.method == method.upper(), ApiLog.route_path == route)
            .order_by(ApiLog.created_at.desc())
            .limit(limit)
            .all()
        )
        if len(logs) < limit:
            legacy = (
                db.query(ApiLog)
                .filter(ApiLog.method == method.upper(), ApiLog.route_path.is_(None))
                .order_by(ApiLog.created_at.desc())
                .limit(limit * 4)
                .all()
            )
            candidates = templates or [route]
            logs.extend(log for log in legacy if match_template(log.endpoint, candidates) == route)
        return logs[:limit]

    @staticmethod
    def infer(db: Session, route: str, method: str, templates: Optional[list] = None, persist: bool = True) -> Dict:
        """Infer request + response schemas for one endpoint."""
        logs = SchemaInferenceService.fetch_logs(db, route, method, templates)

        request_bodies = [log.request_json for log in logs if isinstance(log.request_json, (dict, list))]
        # Only successful responses describe the documented contract (errors have their own shape).
        response_bodies = [
            log.response_json
            for log in logs
            if log.status_code is not None and 200 <= log.status_code < 300 and log.response_json is not None
        ]

        result = {
            "total_logs": len(logs),
            "request": SchemaInferenceService.build_schema_from_bodies(request_bodies),
            "response": SchemaInferenceService.build_schema_from_bodies(response_bodies),
            "request_samples": len(request_bodies),
            "response_samples": len(response_bodies),
        }

        if persist:
            for location in ("request", "response"):
                samples = result[f"{location}_samples"]
                if samples:
                    SchemaInferenceService._persist(db, route, method, location, result[location], samples)
        return result

    @staticmethod
    def _persist(db: Session, route: str, method: str, location: str, schema: Dict, samples: int) -> None:
        schema_hash = SchemaInferenceService.compute_hash(schema)
        latest = (
            db.query(InferredSchema)
            .filter(
                InferredSchema.endpoint == route,
                InferredSchema.method == method,
                InferredSchema.location == location,
            )
            .order_by(InferredSchema.computed_at.desc())
            .first()
        )
        if latest and latest.schema_hash == schema_hash:
            latest.sample_size = samples
        else:
            db.add(
                InferredSchema(
                    endpoint=route,
                    method=method,
                    location=location,
                    schema_json=schema,
                    sample_size=samples,
                    schema_hash=schema_hash,
                )
            )
        db.commit()

    @staticmethod
    def run_inference(endpoint: str, method: str) -> Dict:
        """Legacy entry point: response schema for an endpoint (opens its own session)."""
        from app.database.session import SessionLocal

        db = SessionLocal()
        try:
            return SchemaInferenceService.infer(db, endpoint, method)["response"]
        finally:
            db.close()
