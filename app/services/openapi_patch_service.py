"""Applies generated OpenAPI patches to the live spec and writes the result to disk."""
import copy
import json
from typing import List, Optional

from app.config import settings
from app.utils.schema_utils import extract_json


class OpenAPIPatchService:
    @staticmethod
    def coerce_patch(patch) -> Optional[dict]:
        """Accept dicts, JSON strings and legacy LLM output that wrapped JSON in prose."""
        if isinstance(patch, str):
            patch = extract_json(patch)
        if isinstance(patch, dict) and "paths" not in patch and isinstance(patch.get("openapi_patch"), dict):
            patch = patch["openapi_patch"]
        if isinstance(patch, dict) and isinstance(patch.get("paths"), dict) and patch["paths"]:
            return patch
        return None

    @staticmethod
    def merge(base: dict, patch: dict) -> dict:
        """Deep-merge `patch` into `base`. A `schema` node is replaced, never merged,
        so a `$ref` cannot end up next to inline properties."""
        for key, value in patch.items():
            if key == "schema" or not isinstance(value, dict) or not isinstance(base.get(key), dict):
                base[key] = copy.deepcopy(value)
            else:
                OpenAPIPatchService.merge(base[key], value)
        return base

    @staticmethod
    def changed_operations(patch: dict) -> List[str]:
        return [
            f"{method.upper()} {path}"
            for path, methods in patch.get("paths", {}).items()
            for method in methods
        ]

    @staticmethod
    def apply_patch(base_spec: dict, patch, output_path: Optional[str] = None) -> dict:
        patch = OpenAPIPatchService.coerce_patch(patch)
        if patch is None:
            raise ValueError("Patch is empty or not a valid OpenAPI fragment with a 'paths' object.")
        output_path = output_path or settings.GENERATED_SPEC_PATH
        spec = OpenAPIPatchService.merge(copy.deepcopy(base_spec), patch)
        spec.setdefault("info", {})
        spec["info"]["x-patched"] = True

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)

        return {
            "message": "Patch applied successfully",
            "generated_spec_path": output_path,
            "changed_operations": OpenAPIPatchService.changed_operations(patch),
            "spec": spec,
        }
