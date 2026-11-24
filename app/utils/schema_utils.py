"""Helpers for the flattened field-path notation shared by inference, extraction and drift.

Paths look like:
    name                -> top-level field
    address.city        -> nested object field
    tags[]              -> items of an array field
    orders[].total      -> field of objects inside an array
    [].id               -> field of objects when the whole body is an array
"""
import json
import re
from typing import Optional, Tuple

PY_TYPES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "object": "Dict[str, Any]",
    "array": "List[Any]",
}


def join_path(parent: str, name: str) -> str:
    return f"{parent}.{name}" if parent else name


def split_parent(path: str) -> Tuple[str, str]:
    """'a.b' -> ('a', 'b'); 'a[].b' -> ('a[]', 'b'); 'name' -> ('', 'name')."""
    if "." not in path:
        return "", path
    parent, _, name = path.rpartition(".")
    return parent, name


def parent_of(path: str) -> str:
    return split_parent(path)[0]


def depth(path: str) -> int:
    return path.count(".") + path.count("[]")


def ancestors(path: str):
    """Yield every container path above `path` (closest first), excluding the root ''."""
    current = path
    while True:
        parent = parent_of(current)
        if not parent:
            return
        yield parent
        if parent.endswith("[]"):
            base = parent[:-2]
            if base:
                yield base
            parent = base
        if not parent:
            return
        current = parent


def types_compatible(expected: Optional[str], observed: list) -> bool:
    """Is every observed (non-null) runtime type acceptable for the documented type?"""
    if not expected or expected in {"any", "unknown"}:
        return True
    allowed = {expected}
    if expected == "number":
        allowed.add("integer")
    return all(t in allowed for t in observed if t != "null")


def runtime_to_json_schema(runtime: dict) -> dict:
    """Rebuild a JSON Schema (OpenAPI 3.1 flavour) from a flattened runtime schema."""
    is_array_root = any(p == "[]" or p.startswith("[].") for p in runtime)
    root: dict = {"type": "array", "items": {}} if is_array_root else {"type": "object", "properties": {}}
    field_nodes: dict = {"": root}

    def container(path: str) -> dict:
        """Return the object schema that holds children of `path`."""
        if path.endswith("[]"):
            base_node = node_for(path[:-2])
            base_node["type"] = "array"
            items = base_node.setdefault("items", {})
            items.setdefault("type", "object")
            items.setdefault("properties", {})
            return items
        node = node_for(path)
        node["type"] = "object"
        node.setdefault("properties", {})
        return node

    def node_for(path: str) -> dict:
        if path in field_nodes:
            return field_nodes[path]
        parent, name = split_parent(path)
        holder = container(parent)
        node = holder["properties"].setdefault(name, {})
        field_nodes[path] = node
        return node

    for path in sorted(runtime, key=depth):
        info = runtime[path]
        if path.endswith("[]"):
            continue  # array items are described through their parent / children

        node = node_for(path)
        types = [t for t in info.get("types", []) if t != "null"]
        nullable = info.get("nullable", False)
        if "object" in types or "array" in types:
            node["type"] = types[0]
            if types[0] == "array" and info.get("item_types"):
                node["items"] = _type_schema(info["item_types"], False)
            if nullable:
                node["nullable_hint"] = True
        else:
            node.update(_type_schema(types, nullable))

        parent, name = split_parent(path)
        if info.get("required"):
            holder = container(parent)
            holder.setdefault("required", [])
            if name not in holder["required"]:
                holder["required"].append(name)

    return _finalize(root)


def _type_schema(types: list, nullable: bool) -> dict:
    variants = [{"type": t} for t in sorted(set(types))] or [{}]
    if nullable:
        variants.append({"type": "null"})
    if len(variants) == 1:
        return dict(variants[0])
    return {"anyOf": variants}


def _finalize(schema: dict) -> dict:
    """Turn helper markers into valid JSON schema and sort keys for stable output."""
    if not isinstance(schema, dict):
        return schema
    if schema.pop("nullable_hint", False):
        inner = {k: v for k, v in schema.items()}
        schema.clear()
        schema["anyOf"] = [_finalize(inner), {"type": "null"}]
        return schema
    if "properties" in schema:
        schema["properties"] = {k: _finalize(v) for k, v in sorted(schema["properties"].items())}
    if "items" in schema:
        schema["items"] = _finalize(schema["items"])
    if "anyOf" in schema:
        schema["anyOf"] = [_finalize(v) for v in schema["anyOf"]]
    if "required" in schema:
        schema["required"] = sorted(schema["required"])
    return schema


def extract_json(text):
    """Best-effort extraction of a JSON object from LLM output (handles ``` fences and prose)."""
    if text is None:
        return None
    if isinstance(text, (dict, list)):
        return text
    text = str(text).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except ValueError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except ValueError:
            return None
    return None


def path_template_regex(template: str) -> re.Pattern:
    """'/api/users/{user_id}' -> regex matching '/api/users/42'."""
    parts = re.split(r"(\{[^}]+\})", template)
    pattern = "".join("[^/]+" if p.startswith("{") and p.endswith("}") else re.escape(p) for p in parts)
    return re.compile(f"^{pattern}/?$")


def match_template(path: str, templates) -> Optional[str]:
    if path in templates:
        return path
    for template in templates:
        if "{" in template and path_template_regex(template).match(path):
            return template
    return None
