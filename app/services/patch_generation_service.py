"""Generates actionable fixes for a drift report.

* OpenAPI patch  - a valid JSON fragment (``{"paths": ...}``) describing the observed
  contract. It can be merged into the live spec with OpenAPIPatchService.
* Backend patch  - ready-to-paste Pydantic models matching the observed payloads.

Both are derived deterministically from captured traffic, so they are always valid and
reproducible (no hallucinated fields).
"""
import keyword
import re
from typing import Dict, List, Tuple

from app.utils.schema_utils import PY_TYPES, runtime_to_json_schema

IGNORED_SEGMENTS = {"api", "v1", "v2", "v3"}


def _pascal(text: str) -> str:
    words = re.split(r"[^0-9a-zA-Z]+", text)
    return "".join(w[:1].upper() + w[1:] for w in words if w)


def _identifier(name: str) -> str:
    ident = re.sub(r"\W", "_", name)
    if not ident or ident[0].isdigit() or ident.startswith("_"):
        ident = f"field_{ident.lstrip('_')}"
    if keyword.iskeyword(ident):
        ident += "_"
    return ident


def model_base_name(endpoint: str, method: str) -> str:
    segments = [s for s in endpoint.strip("/").split("/") if s and not s.startswith("{")]
    segments = [s for s in segments if s.lower() not in IGNORED_SEGMENTS] or ["Root"]
    return _pascal(segments[-1]) + method.title()


def expected_to_runtime_shape(expected: dict) -> dict:
    """Convert a documented flattened schema into the runtime-schema shape."""
    shaped = {}
    for path, info in expected.items():
        types = info.get("alt_types") or ([info["type"]] if info.get("type") not in (None, "any") else [])
        entry = {"types": types, "nullable": bool(info.get("nullable")), "required": bool(info.get("required"))}
        if info.get("item_type"):
            entry["item_types"] = [info["item_type"]]
        shaped[path] = entry
    return shaped


class _ModelWriter:
    def __init__(self):
        self.classes: List[Tuple[str, List[str]]] = []
        self.names = set()

    def unique(self, name: str) -> str:
        candidate, n = name, 2
        while candidate in self.names:
            candidate, n = f"{name}{n}", n + 1
        self.names.add(candidate)
        return candidate

    def py_type(self, schema: dict, hint: str) -> str:
        if not schema:
            return "Any"
        if "anyOf" in schema:
            variants = schema["anyOf"]
            non_null = [v for v in variants if v.get("type") != "null"]
            inner = list(dict.fromkeys(self.py_type(v, hint) for v in non_null)) or ["Any"]
            result = inner[0] if len(inner) == 1 else f"Union[{', '.join(inner)}]"
            return f"Optional[{result}]" if len(non_null) < len(variants) else result
        kind = schema.get("type")
        if kind == "object":
            return self.model(hint, schema) if schema.get("properties") else "Dict[str, Any]"
        if kind == "array":
            items = schema.get("items") or {}
            return f"List[{self.py_type(items, hint + 'Item') if items else 'Any'}]"
        return PY_TYPES.get(kind, "Any")

    def model(self, name: str, schema: dict) -> str:
        name = self.unique(name)
        required = set(schema.get("required", []))
        lines = [f"class {name}(BaseModel):"]
        for prop, sub in schema.get("properties", {}).items():
            ident = _identifier(prop)
            annotation = self.py_type(sub, name + _pascal(prop))
            is_required = prop in required
            if not is_required and not annotation.startswith("Optional["):
                annotation = f"Optional[{annotation}]"
            if ident != prop:
                default = f' = Field({"..." if is_required else "None"}, alias="{prop}")'
            else:
                default = "" if is_required else " = None"
            lines.append(f"    {ident}: {annotation}{default}")
        if len(lines) == 1:
            lines.append("    pass")
        self.classes.append((name, lines))
        return name


class PatchGenerationService:
    @staticmethod
    def location_schema(report: dict, location: str) -> dict:
        """The JSON schema that should be documented for `location`."""
        runtime = report["runtime_schema"].get(location) or {}
        if location == "response":
            return runtime_to_json_schema(runtime)
        # Requests: keep the documented contract and add fields clients really send.
        merged = expected_to_runtime_shape(report["expected_schema"].get("request") or {})
        for path, info in runtime.items():
            if path not in merged:
                merged[path] = {**info, "required": False}
        return runtime_to_json_schema(merged)

    @staticmethod
    def openapi_patch(report: dict) -> dict:
        locations = {i["location"] for i in report.get("issues", [])}
        if "endpoint" in locations:
            locations |= {"request", "response"}
        operation: Dict = {}
        if "response" in locations and report["runtime_schema"].get("response"):
            status = str(report.get("response_status") or "200")
            operation["responses"] = {
                status: {
                    "description": "Successful Response",
                    "content": {"application/json": {"schema": PatchGenerationService.location_schema(report, "response")}},
                }
            }
        if "request" in locations and report["runtime_schema"].get("request"):
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": PatchGenerationService.location_schema(report, "request")}},
            }
        if not operation:
            return {}
        return {"paths": {report["endpoint"]: {report["method"].lower(): operation}}}

    @staticmethod
    def backend_patch(report: dict) -> str:
        endpoint, method = report["endpoint"], report["method"]
        issues = report.get("issues", [])
        locations = {i["location"] for i in issues}
        if "endpoint" in locations:
            locations |= {"request", "response"}
        base = model_base_name(endpoint, method)
        writer = _ModelWriter()
        usage = []

        for location in ("request", "response"):
            if location not in locations or not report["runtime_schema"].get(location):
                continue
            schema = PatchGenerationService.location_schema(report, location)
            class_name = f"{base}{location.title()}"
            if schema.get("type") == "array":
                item = schema.get("items") or {}
                inner = writer.model(f"{class_name}Item", item) if item.get("properties") else "Any"
                root_type = f"List[{inner}]"
            else:
                root_type = writer.model(class_name, schema)
            if location == "response":
                usage.append(f'@app.{method.lower()}("{endpoint}", response_model={root_type})')
            else:
                usage.append(f"def handler(payload: {root_type}): ...")

        samples = report.get("sample_size", {})
        header = [
            f"# Suggested Pydantic models for {method} {endpoint}",
            f"# Derived from {samples.get('response', 0)} response and {samples.get('request', 0)} request sample(s).",
            "#",
            "# Detected issues:",
        ]
        for issue in issues[:25]:
            header.append(f"#   [{issue['severity']:<6}] {issue['location']}: {issue['message']}")
        if len(issues) > 25:
            header.append(f"#   ... and {len(issues) - 25} more")
        if usage:
            header += ["#", "# Usage:"] + [f"#   {line}" for line in usage]

        body = []
        for _, lines in writer.classes:
            body.append("\n".join(lines))

        imports = [
            "from typing import Any, Dict, List, Optional, Union",
            "",
            "from pydantic import BaseModel, Field",
        ]
        if not body:
            body = ["# No payload changes are required for this drift."]
        return "\n".join(header) + "\n\n" + "\n".join(imports) + "\n\n\n" + "\n\n\n".join(body) + "\n"

    @staticmethod
    def generate(report: dict) -> dict:
        return {
            "openapi_patch": PatchGenerationService.openapi_patch(report),
            "backend_patch": PatchGenerationService.backend_patch(report),
        }
