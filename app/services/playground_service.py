"""Builds request templates for the API playground from the live OpenAPI spec."""
from typing import Any

from fastapi import FastAPI

from app.config import settings
from app.services.openapi_extraction_service import HTTP_METHODS, MAX_REF_DEPTH, OpenAPIExtractionService

STRING_FORMATS = {
    "email": "user@example.com",
    "date": "2026-01-31",
    "date-time": "2026-01-31T12:00:00Z",
    "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "uri": "https://example.com",
}


def example_from_schema(spec: dict, schema: dict, name: str = "", depth: int = 0) -> Any:
    schema = OpenAPIExtractionService.resolve_schema(spec, schema or {})
    if depth > MAX_REF_DEPTH:
        return None
    for key in ("example", "default"):
        if key in schema and schema[key] is not None:
            return schema[key]
    if schema.get("examples"):
        examples = schema["examples"]
        return examples[0] if isinstance(examples, list) else next(iter(examples.values()), None)
    if schema.get("enum"):
        return schema["enum"][0]

    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        for variant in variants:
            resolved = OpenAPIExtractionService.resolve_schema(spec, variant)
            if resolved.get("type") != "null":
                return example_from_schema(spec, resolved, name, depth + 1)
        return None
    if schema.get("allOf"):
        merged: dict = {"type": "object", "properties": {}}
        for part in schema["allOf"]:
            part = OpenAPIExtractionService.resolve_schema(spec, part)
            merged["properties"].update(part.get("properties", {}))
        return example_from_schema(spec, merged, name, depth + 1)

    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((t for t in kind if t != "null"), None)
    if kind == "object" or "properties" in schema:
        return {
            prop: example_from_schema(spec, sub, prop, depth + 1)
            for prop, sub in schema.get("properties", {}).items()
        }
    if kind == "array":
        return [example_from_schema(spec, schema.get("items", {}), name, depth + 1)]
    if kind == "integer":
        return max(1, int(schema.get("minimum", 1) or 1))
    if kind == "number":
        return 9.99
    if kind == "boolean":
        return True
    if kind == "string":
        if schema.get("format") in STRING_FORMATS:
            return STRING_FORMATS[schema["format"]]
        if "email" in name.lower():
            return STRING_FORMATS["email"]
        return f"example {name}".strip() if name else "string"
    return None


class PlaygroundService:
    @staticmethod
    def operations(app: FastAPI, monitored_only: bool = True) -> list:
        spec = OpenAPIExtractionService.live_spec(app)
        operations = []
        for path, methods in sorted(spec.get("paths", {}).items()):
            monitored = any(path.startswith(p) for p in settings.LOG_INCLUDE_PREFIXES)
            if monitored_only and not monitored:
                continue
            for method, details in methods.items():
                if method.lower() not in HTTP_METHODS:
                    continue
                path_params, query_params = [], []
                for param in details.get("parameters", []):
                    param = OpenAPIExtractionService.resolve_schema(spec, param)
                    schema = OpenAPIExtractionService.resolve_schema(spec, param.get("schema", {}))
                    entry = {
                        "name": param.get("name"),
                        "type": schema.get("type", "string"),
                        "required": bool(param.get("required")),
                        "example": example_from_schema(spec, schema, param.get("name", "")),
                        "description": param.get("description"),
                    }
                    if param.get("in") == "path":
                        path_params.append(entry)
                    elif param.get("in") == "query":
                        query_params.append(entry)

                body = None
                request_body = OpenAPIExtractionService.resolve_schema(spec, details.get("requestBody") or {})
                for media_type, media in (request_body.get("content") or {}).items():
                    if "json" in media_type:
                        body = example_from_schema(spec, media.get("schema", {}))
                        break

                operations.append(
                    {
                        "id": f"{method.upper()} {path}",
                        "method": method.upper(),
                        "path": path,
                        "summary": details.get("summary"),
                        "tags": details.get("tags", []),
                        "monitored": monitored,
                        "path_params": path_params,
                        "query_params": query_params,
                        "has_body": body is not None,
                        "body_example": body,
                    }
                )
        return operations
