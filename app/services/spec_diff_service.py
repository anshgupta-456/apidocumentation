"""Compares two OpenAPI spec versions and highlights breaking changes."""
from app.services.openapi_extraction_service import OpenAPIExtractionService


class SpecDiffService:
    @staticmethod
    def _field_changes(location: str, old: dict, new: dict) -> list:
        changes = []
        for field in sorted(set(new) - set(old)):
            info = new[field]
            breaking = location == "request" and info.get("required", False)
            changes.append(
                {
                    "location": location,
                    "field": field,
                    "change": "added",
                    "old": None,
                    "new": info.get("type"),
                    "breaking": breaking,
                }
            )
        for field in sorted(set(old) - set(new)):
            changes.append(
                {
                    "location": location,
                    "field": field,
                    "change": "removed",
                    "old": old[field].get("type"),
                    "new": None,
                    "breaking": location == "response",
                }
            )
        for field in sorted(set(old) & set(new)):
            o, n = old[field], new[field]
            if o.get("type") != n.get("type"):
                changes.append(
                    {
                        "location": location,
                        "field": field,
                        "change": "type_changed",
                        "old": o.get("type"),
                        "new": n.get("type"),
                        "breaking": True,
                    }
                )
            if bool(o.get("required")) != bool(n.get("required")):
                now_required = bool(n.get("required"))
                changes.append(
                    {
                        "location": location,
                        "field": field,
                        "change": "now_required" if now_required else "now_optional",
                        "old": bool(o.get("required")),
                        "new": now_required,
                        "breaking": now_required if location == "request" else not now_required,
                    }
                )
            if bool(o.get("nullable")) != bool(n.get("nullable")):
                now_nullable = bool(n.get("nullable"))
                changes.append(
                    {
                        "location": location,
                        "field": field,
                        "change": "now_nullable" if now_nullable else "now_non_nullable",
                        "old": bool(o.get("nullable")),
                        "new": now_nullable,
                        "breaking": now_nullable if location == "response" else not now_nullable,
                    }
                )
        return changes

    @staticmethod
    def diff(old_spec: dict, new_spec: dict) -> dict:
        old = OpenAPIExtractionService.normalize_spec(old_spec or {})
        new = OpenAPIExtractionService.normalize_spec(new_spec or {})
        old_ops = {(p, m) for p, methods in old.items() for m in methods}
        new_ops = {(p, m) for p, methods in new.items() for m in methods}

        added = [{"endpoint": p, "method": m} for p, m in sorted(new_ops - old_ops)]
        removed = [{"endpoint": p, "method": m, "breaking": True} for p, m in sorted(old_ops - new_ops)]

        changed = []
        for path, method in sorted(old_ops & new_ops):
            changes = []
            for location in ("request", "response"):
                changes += SpecDiffService._field_changes(
                    location, old[path][method].get(location, {}), new[path][method].get(location, {})
                )
            if changes:
                changed.append({"endpoint": path, "method": method, "changes": changes})

        breaking = len(removed) + sum(1 for op in changed for c in op["changes"] if c["breaking"])
        return {
            "summary": {
                "added_endpoints": len(added),
                "removed_endpoints": len(removed),
                "changed_endpoints": len(changed),
                "breaking_changes": breaking,
                "identical": not (added or removed or changed),
            },
            "added_endpoints": added,
            "removed_endpoints": removed,
            "changed_endpoints": changed,
        }
