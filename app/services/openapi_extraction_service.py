"""Extracts and normalizes the documented contract from the FastAPI OpenAPI spec."""
import copy
import hashlib
import json
from typing import Dict, Optional, Tuple

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.database.models import OpenAPISpec
from app.utils.schema_utils import join_path

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
MAX_REF_DEPTH = 12


class OpenAPIExtractionService:
    @staticmethod
    def compute_hash(spec: dict) -> str:
        """Hash the full OpenAPI spec for versioning."""
        return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()

    # ------------------------------------------------------------------ $ref handling
    @staticmethod
    def resolve_schema(spec: dict, schema: dict, _depth: int = 0) -> dict:
        """Resolve a (possibly chained) local $ref such as '#/components/schemas/User'."""
        while isinstance(schema, dict) and "$ref" in schema and _depth < MAX_REF_DEPTH:
            _, _, path = schema["$ref"].partition("#/")
            resolved = spec
            for part in path.split("/"):
                resolved = resolved.get(part, {}) if isinstance(resolved, dict) else {}
            extra = {k: v for k, v in schema.items() if k != "$ref"}
            schema = {**resolved, **extra}
            _depth += 1
        return schema if isinstance(schema, dict) else {}

    # ------------------------------------------------------------------ normalization
    @staticmethod
    def _describe(spec: dict, info: dict, depth: int = 0) -> Tuple[dict, Optional[dict]]:
        """Return ({type, nullable, format, enum}, object_or_array_schema_to_recurse)."""
        info = OpenAPIExtractionService.resolve_schema(spec, info, depth)
        nullable = bool(info.get("nullable", False))
        recurse = None

        if "allOf" in info:
            merged: Dict = {"type": "object", "properties": {}, "required": []}
            for part in info["allOf"]:
                part = OpenAPIExtractionService.resolve_schema(spec, part, depth + 1)
                merged["properties"].update(part.get("properties", {}))
                merged["required"].extend(part.get("required", []))
                if part.get("type") and part.get("type") != "object":
                    merged["type"] = part["type"]
            info = {**{k: v for k, v in info.items() if k != "allOf"}, **merged}

        variants = info.get("anyOf") or info.get("oneOf")
        if variants:
            types = []
            for variant in variants:
                variant = OpenAPIExtractionService.resolve_schema(spec, variant, depth + 1)
                vtype = variant.get("type")
                if vtype == "null":
                    nullable = True
                    continue
                if vtype is None and "properties" in variant:
                    vtype = "object"
                if vtype:
                    types.append(vtype)
                if vtype in {"object", "array"} and recurse is None:
                    recurse = variant
            field_type = types[0] if len(types) == 1 else ("any" if not types else types[0])
            desc = {"type": field_type, "nullable": nullable}
            if len(types) > 1:
                desc["alt_types"] = types
            return desc, recurse

        field_type = info.get("type")
        if isinstance(field_type, list):  # OpenAPI 3.1: ["string", "null"]
            nullable = nullable or "null" in field_type
            non_null = [t for t in field_type if t != "null"]
            field_type = non_null[0] if non_null else "any"
        if field_type is None:
            field_type = "object" if "properties" in info or "additionalProperties" in info else "any"

        desc = {"type": field_type, "nullable": nullable}
        if info.get("format"):
            desc["format"] = info["format"]
        if info.get("enum"):
            desc["enum"] = info["enum"]
        if field_type in {"object", "array"}:
            recurse = info
        return desc, recurse

    @staticmethod
    def flatten(spec: dict, schema: dict, prefix: str = "", out: Optional[dict] = None, depth: int = 0) -> dict:
        """Flatten an object/array schema into {path: {type, nullable, required, ...}}."""
        out = {} if out is None else out
        if depth > MAX_REF_DEPTH:
            return out
        schema = OpenAPIExtractionService.resolve_schema(spec, schema, depth)

        if schema.get("type") == "array" or "items" in schema:
            items = OpenAPIExtractionService.resolve_schema(spec, schema.get("items", {}), depth + 1)
            desc, nested = OpenAPIExtractionService._describe(spec, items, depth + 1)
            if nested is not None and desc["type"] == "object":
                OpenAPIExtractionService.flatten(spec, nested, f"{prefix}[]", out, depth + 1)
            return out

        if "allOf" in schema:
            _, merged = OpenAPIExtractionService._describe(spec, schema, depth)
            schema = merged or schema

        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        for name, info in properties.items():
            path = join_path(prefix, name)
            desc, nested = OpenAPIExtractionService._describe(spec, info, depth + 1)
            desc["required"] = name in required
            if desc["type"] == "array" and nested is not None:
                item_schema = OpenAPIExtractionService.resolve_schema(spec, nested.get("items", {}), depth + 1)
                item_desc, _ = OpenAPIExtractionService._describe(spec, item_schema, depth + 1)
                if item_desc["type"] not in {"object", "any"}:
                    desc["item_type"] = item_desc["type"]
            if desc["type"] == "object" and nested is not None and not nested.get("properties"):
                desc["free_form"] = True  # Dict[str, Any] etc.
            out[path] = desc
            if nested is not None and nested.get("properties") or (desc["type"] == "array" and nested is not None):
                OpenAPIExtractionService.flatten(spec, nested, path, out, depth + 1)
        return out

    @staticmethod
    def normalize_schema(schema: dict, spec: Optional[dict] = None) -> dict:
        """Backward compatible: flatten a schema into comparable normalized fields."""
        return OpenAPIExtractionService.flatten(spec or {}, schema)

    @staticmethod
    def _json_schema(spec: dict, content: dict) -> Optional[dict]:
        for media_type, media in (content or {}).items():
            if "json" in media_type:
                return media.get("schema", {})
        return None

    @staticmethod
    def _is_free_form(schema: dict) -> bool:
        """An object schema without declared properties (e.g. Dict[str, Any])."""
        return schema.get("type") == "object" and not schema.get("properties") and "allOf" not in schema

    @staticmethod
    def normalize_operation(spec: dict, details: dict) -> dict:
        responses = details.get("responses", {})
        status = next((code for code in sorted(responses) if str(code).startswith("2")), None)

        response_fields, response_documented, response_free_form = {}, False, False
        if status is not None:
            schema = OpenAPIExtractionService._json_schema(spec, responses[status].get("content", {}))
            resolved = OpenAPIExtractionService.resolve_schema(spec, schema or {})
            response_documented = bool(resolved)  # `{}` means "any" -> undocumented shape
            if resolved:
                response_free_form = OpenAPIExtractionService._is_free_form(resolved)
                response_fields = OpenAPIExtractionService.flatten(spec, resolved)

        request_fields, request_documented, request_free_form = {}, False, False
        body = OpenAPIExtractionService.resolve_schema(spec, details.get("requestBody", {}) or {})
        schema = OpenAPIExtractionService._json_schema(spec, body.get("content", {}))
        if schema is not None:
            request_documented = True
            resolved = OpenAPIExtractionService.resolve_schema(spec, schema)
            request_free_form = not resolved or OpenAPIExtractionService._is_free_form(resolved)
            request_fields = OpenAPIExtractionService.flatten(spec, resolved)

        return {
            "summary": details.get("summary"),
            "operation_id": details.get("operationId"),
            "tags": details.get("tags", []),
            "response_status": status,
            "response_documented": response_documented,
            "response_free_form": response_free_form,
            "request_documented": request_documented,
            "request_free_form": request_free_form,
            "response": response_fields,
            "request": request_fields,
        }

    @staticmethod
    def normalize_spec(spec: dict) -> Dict[str, Dict[str, dict]]:
        normalized: Dict[str, Dict[str, dict]] = {}
        for path, methods in spec.get("paths", {}).items():
            normalized[path] = {}
            for method, details in methods.items():
                if method.lower() not in HTTP_METHODS:
                    continue
                normalized[path][method.upper()] = OpenAPIExtractionService.normalize_operation(spec, details)
        return normalized

    @staticmethod
    def live_spec(app: FastAPI) -> dict:
        return copy.deepcopy(app.openapi())

    @staticmethod
    def extracted_paths(app: FastAPI):
        """Return (raw spec, normalized paths) for the running application."""
        spec = OpenAPIExtractionService.live_spec(app)
        return spec, OpenAPIExtractionService.normalize_spec(spec)

    # ------------------------------------------------------------------ persistence
    @staticmethod
    def latest(db: Session) -> Optional[OpenAPISpec]:
        return db.query(OpenAPISpec).order_by(OpenAPISpec.extracted_at.desc()).first()

    @staticmethod
    def save_to_db(db: Session, spec: dict, normalized_paths: dict) -> Tuple[OpenAPISpec, bool]:
        """Store a new spec version. Returns (record, created) and skips identical versions."""
        version_hash = OpenAPIExtractionService.compute_hash(spec)
        latest = OpenAPIExtractionService.latest(db)
        if latest and latest.version_hash == version_hash:
            return latest, False
        entry = OpenAPISpec(version_hash=version_hash, spec_json=spec, normalized_paths=normalized_paths)
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry, True

    @staticmethod
    def run_extraction(app: FastAPI, db: Session):
        """Extract the live spec, store it if it changed and diff it against the previous one."""
        from app.services.spec_diff_service import SpecDiffService

        spec, normalized = OpenAPIExtractionService.extracted_paths(app)
        previous = OpenAPIExtractionService.latest(db)
        record, created = OpenAPIExtractionService.save_to_db(db, spec, normalized)
        diff = None
        if created and previous is not None:
            diff = SpecDiffService.diff(previous.spec_json, spec)
        return {
            "spec": spec,
            "normalized": normalized,
            "record": record,
            "created": created,
            "diff": diff,
        }
