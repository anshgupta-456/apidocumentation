"""Schema drift engine: compares documented contracts with observed runtime behaviour."""
import hashlib
import json
import logging
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import ApiLog, DriftEvents, utcnow
from app.services.openapi_extraction_service import OpenAPIExtractionService
from app.services.schema_inference_service import SchemaInferenceService
from app.utils.schema_utils import ancestors, depth, match_template, parent_of, types_compatible

logger = logging.getLogger(__name__)

CATEGORY_KEYS = (
    "missing_in_runtime",
    "missing_in_openapi",
    "type_mismatches",
    "nullable_mismatches",
    "required_mismatches",
)
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
ACTIVE_STATUSES = ("open", "acknowledged")


def empty_categories() -> Dict[str, list]:
    return {key: [] for key in CATEGORY_KEYS}


def normalize_endpoint(endpoint: str) -> str:
    endpoint = (endpoint or "").strip()
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    if len(endpoint) > 1:
        endpoint = endpoint.rstrip("/")
    return endpoint


def normalize_drift_detail(detail) -> dict:
    """Return drift details in the v2 shape, converting records stored by older versions."""
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except ValueError:
            detail = {}
    detail = detail if isinstance(detail, dict) else {}
    if "issues" in detail:
        detail.setdefault("response", empty_categories())
        detail.setdefault("request", empty_categories())
        return detail

    categories = {key: detail.get(key, []) for key in CATEGORY_KEYS}
    return {
        "version": 1,
        "issues": SchemaDriftService.build_issues("response", categories, {}, {}),
        "response": categories,
        "request": empty_categories(),
        "sample_size": {},
        "runtime_schema": {},
        "expected_schema": {},
    }


class SchemaDriftService:
    # ------------------------------------------------------------------ comparison
    @staticmethod
    def _container_observed(container: str, runtime: dict) -> bool:
        if container == "":
            return bool(runtime)
        if container.endswith("[]"):
            return any(path.startswith(container + ".") for path in runtime)
        info = runtime.get(container)
        return bool(info and "object" in info.get("types", []))

    @staticmethod
    def compare(expected: dict, runtime: dict, location: str = "response", free_form_root: bool = False) -> dict:
        """Compare a documented flattened schema against an inferred runtime schema.

        Only *contract violations* and *undocumented behaviour* are reported. Things the
        contract allows (an optional field that happens to always be present, a nullable
        field that is never null) are not drift.
        """
        drift = empty_categories()
        if not runtime:
            return drift

        # 1. documented fields never observed
        for field, exp in expected.items():
            if field in runtime:
                continue
            if not SchemaDriftService._container_observed(parent_of(field), runtime):
                continue  # parent never seen -> already reported higher up (or no data)
            if location == "request" and not exp.get("required"):
                continue  # optional request fields are allowed to be omitted
            drift["missing_in_runtime"].append(field)

        # 2. observed fields that are not documented (only the top-most undocumented node)
        free_form = {p for p, d in expected.items() if d.get("free_form") or d.get("type") == "any"}
        reported = set()
        if not free_form_root:
            for field in sorted(runtime, key=depth):
                if field in expected:
                    continue
                if any(a in free_form or a in reported for a in ancestors(field)):
                    continue
                drift["missing_in_openapi"].append(field)
                reported.add(field)

        # 3. attribute comparison for fields present on both sides
        for field, exp in expected.items():
            run = runtime.get(field)
            if run is None:
                continue
            observed_types = [t for t in run.get("types", []) if t != "null"]
            allowed = exp.get("alt_types") or [exp.get("type")]
            bad = [t for t in observed_types if not any(types_compatible(a, [t]) for a in allowed)]
            if bad:
                drift["type_mismatches"].append(
                    {"field": field, "expected": "|".join(a for a in allowed if a), "runtime": observed_types}
                )
            if run.get("nullable") and not exp.get("nullable"):
                drift["nullable_mismatches"].append({"field": field, "expected": False, "runtime": True})
            if exp.get("required") and not run.get("required"):
                drift["required_mismatches"].append(
                    {
                        "field": field,
                        "expected": True,
                        "runtime": False,
                        "presence_percent": run.get("presence_percent"),
                    }
                )
        return drift

    # ------------------------------------------------------------------ issues & severity
    @staticmethod
    def build_issues(location: str, categories: dict, expected: dict, runtime: dict) -> List[dict]:
        is_response = location == "response"
        issues: List[dict] = []

        def add(category, field, severity, message, expected_value=None, observed_value=None):
            issues.append(
                {
                    "location": location,
                    "category": category,
                    "field": field,
                    "severity": severity,
                    "message": message,
                    "expected": expected_value,
                    "observed": observed_value,
                }
            )

        for field in categories.get("missing_in_openapi", []):
            info = runtime.get(field, {})
            types = "|".join(info.get("types", [])) or "unknown"
            if is_response:
                msg = f"Response contains undocumented field '{field}' ({types})."
            else:
                msg = f"Clients send undocumented field '{field}' ({types}); it is silently ignored."
            add("undocumented_field", field, "medium", msg, None, types)

        for field in categories.get("missing_in_runtime", []):
            required = (expected.get(field) or {}).get("required")
            if is_response:
                severity = "high" if required else "low"
                label = "required" if required else "optional"
                msg = f"Documented {label} field '{field}' never appears in real responses."
            else:
                severity = "medium"
                msg = f"Required field '{field}' is never sent by clients (requests fail validation)."
            add("missing_field", field, severity, msg, "present", "absent")

        for item in categories.get("type_mismatches", []):
            observed = item.get("runtime")
            observed = "|".join(observed) if isinstance(observed, list) else str(observed)
            add(
                "type_mismatch",
                item.get("field"),
                "high" if is_response else "medium",
                f"Field '{item.get('field')}' is documented as {item.get('expected')} but observed as {observed}.",
                item.get("expected"),
                observed,
            )

        for item in categories.get("nullable_mismatches", []):
            if item.get("runtime") and not item.get("expected"):
                add(
                    "nullable_mismatch",
                    item.get("field"),
                    "high" if is_response else "medium",
                    f"Field '{item.get('field')}' is not nullable in the spec but null values were observed.",
                    "non-null",
                    "null seen",
                )
            else:  # legacy records only
                add(
                    "nullable_mismatch",
                    item.get("field"),
                    "low",
                    f"Field '{item.get('field')}' nullability differs from the spec.",
                    item.get("expected"),
                    item.get("runtime"),
                )

        for item in categories.get("required_mismatches", []):
            pct = item.get("presence_percent")
            if item.get("expected") and not item.get("runtime"):
                presence = f"present in {pct}% of samples" if pct is not None else "not always present"
                if is_response:
                    msg = f"Required field '{item.get('field')}' is missing from some responses ({presence})."
                else:
                    msg = f"Clients sometimes omit required field '{item.get('field')}' ({presence})."
                add("required_mismatch", item.get("field"), "high" if is_response else "medium", msg, "required", presence)
            else:  # legacy records only
                add(
                    "required_mismatch",
                    item.get("field"),
                    "low",
                    f"Field '{item.get('field')}' is optional in the spec but always present at runtime.",
                    item.get("expected"),
                    item.get("runtime"),
                )
        return issues

    @staticmethod
    def overall_severity(issues: List[dict]) -> Optional[str]:
        if not issues:
            return None
        return max((i["severity"] for i in issues), key=lambda s: SEVERITY_RANK.get(s, 0))

    @staticmethod
    def fingerprint(endpoint: str, method: str, issues: List[dict]) -> str:
        keys = sorted(f"{i['location']}|{i['category']}|{i['field']}" for i in issues)
        raw = json.dumps([endpoint, method, keys])
        return hashlib.sha256(raw.encode()).hexdigest()

    # ------------------------------------------------------------------ analysis
    @staticmethod
    def analyze(db: Session, normalized: dict, endpoint: str, method: str) -> dict:
        method = method.upper()
        templates = list(normalized.keys())
        route = match_template(normalize_endpoint(endpoint), templates) or normalize_endpoint(endpoint)
        inference = SchemaInferenceService.infer(db, route, method, templates)
        operation = normalized.get(route, {}).get(method)

        report = {
            "endpoint": route,
            "method": method,
            "documented": operation is not None,
            "response_status": (operation or {}).get("response_status"),
            "sample_size": {
                "total": inference["total_logs"],
                "request": inference["request_samples"],
                "response": inference["response_samples"],
            },
            "runtime_schema": {"request": inference["request"], "response": inference["response"]},
            "expected_schema": {
                "request": (operation or {}).get("request", {}),
                "response": (operation or {}).get("response", {}),
            },
            "response": empty_categories(),
            "request": empty_categories(),
            "issues": [],
        }

        if inference["total_logs"] == 0:
            report.update(status="no_traffic", has_drift=False, severity=None)
            return report

        issues: List[dict] = []
        if operation is None:
            issues.append(
                {
                    "location": "endpoint",
                    "category": "undocumented_endpoint",
                    "field": None,
                    "severity": "medium",
                    "message": f"{method} {route} receives traffic but is not documented in the OpenAPI spec.",
                    "expected": "documented",
                    "observed": f"{inference['total_logs']} requests",
                }
            )
        else:
            for location in ("response", "request"):
                runtime = inference[location]
                if not inference[f"{location}_samples"] or not runtime:
                    continue
                if not operation[f"{location}_documented"]:
                    issues.append(
                        {
                            "location": location,
                            "category": f"undocumented_{location}",
                            "field": None,
                            "severity": "medium",
                            "message": f"The {location} body is not described in the spec "
                            f"but {len(runtime)} field(s) were observed.",
                            "expected": "schema",
                            "observed": ", ".join(sorted(runtime)[:8]),
                        }
                    )
                    continue
                categories = SchemaDriftService.compare(
                    operation[location], runtime, location, operation.get(f"{location}_free_form", False)
                )
                report[location] = categories
                issues.extend(SchemaDriftService.build_issues(location, categories, operation[location], runtime))

        issues.sort(key=lambda i: (-SEVERITY_RANK.get(i["severity"], 0), i["location"], str(i["field"])))
        report["issues"] = issues
        report["severity"] = SchemaDriftService.overall_severity(issues)
        report["has_drift"] = bool(issues)
        report["status"] = "drift" if issues else "clean"
        return report

    # ------------------------------------------------------------------ persistence
    @staticmethod
    def save_drift(db: Session, report: dict, use_ai: bool = True) -> Tuple[DriftEvents, bool]:
        """Persist a drift report. Repeated identical drift updates the active event instead."""
        from app.services.ai_explanation_service import AIExplanationService
        from app.services.patch_generation_service import PatchGenerationService

        endpoint, method, issues = report["endpoint"], report["method"], report["issues"]
        fingerprint = SchemaDriftService.fingerprint(endpoint, method, issues)
        stored_detail = {
            "version": 2,
            "issues": issues,
            "response": report["response"],
            "request": report["request"],
            "sample_size": report["sample_size"],
            "runtime_schema": report["runtime_schema"],
            "expected_schema": report["expected_schema"],
            "response_status": report.get("response_status"),
        }

        existing = (
            db.query(DriftEvents)
            .filter(
                DriftEvents.endpoint == endpoint,
                DriftEvents.method == method,
                DriftEvents.fingerprint == fingerprint,
                DriftEvents.status.in_(ACTIVE_STATUSES),
            )
            .order_by(DriftEvents.detected_at.desc())
            .first()
        )
        if existing:
            existing.occurrences = (existing.occurrences or 1) + 1
            existing.last_seen_at = utcnow()
            existing.severity = report["severity"]
            existing.drift_detail = stored_detail
            db.commit()
            return existing, False

        explanation, provider = AIExplanationService.explain(endpoint, method, report, use_ai=use_ai)
        patches = PatchGenerationService.generate(report)

        event = DriftEvents(
            endpoint=endpoint,
            method=method,
            severity=report["severity"],
            drift_detail=stored_detail,
            ai_explanation=json.dumps(explanation),
            openapi_patch=json.dumps(patches["openapi_patch"]),
            backend_patch=patches["backend_patch"],
            detected_at=utcnow(),
            status="open",
            issue_count=len(issues),
            fingerprint=fingerprint,
            occurrences=1,
            last_seen_at=utcnow(),
            ai_provider=provider,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event, True

    # ------------------------------------------------------------------ orchestration
    @staticmethod
    def observed_operations(db: Session, templates: list) -> List[Tuple[str, str]]:
        """Distinct (route template, method) pairs that have captured traffic."""
        rows = db.query(func.coalesce(ApiLog.route_path, ApiLog.endpoint), ApiLog.method).distinct().all()
        seen = []
        for path, method in rows:
            route = match_template(path, templates) or path
            key = (route, method.upper())
            if key not in seen:
                seen.append(key)
        return sorted(seen)

    @staticmethod
    def _result(report: dict, event: Optional[DriftEvents], created: bool, full: bool) -> dict:
        result = {
            "endpoint": report["endpoint"],
            "method": report["method"],
            "status": report["status"],
            "has_drift": report["has_drift"],
            "severity": report.get("severity"),
            "issue_count": len(report["issues"]),
            "issues": report["issues"],
            "sample_size": report["sample_size"],
            "event_id": str(event.id) if event else None,
            "event_created": created,
        }
        if full:
            result["drift_report"] = report
        return result

    @staticmethod
    def detect(
        app: FastAPI,
        db: Session,
        endpoint: str,
        method: Optional[str] = None,
        save: bool = True,
        use_ai: bool = True,
    ) -> List[dict]:
        _, normalized = OpenAPIExtractionService.extracted_paths(app)
        templates = list(normalized.keys())
        route = match_template(normalize_endpoint(endpoint), templates) or normalize_endpoint(endpoint)

        if method:
            methods = [method.upper()]
        else:
            methods = [m for r, m in SchemaDriftService.observed_operations(db, templates) if r == route]
            if not methods:
                methods = sorted(normalized.get(route, {}).keys())

        results = []
        for m in methods:
            report = SchemaDriftService.analyze(db, normalized, route, m)
            event, created = (None, False)
            if save and report["has_drift"]:
                event, created = SchemaDriftService.save_drift(db, report, use_ai=use_ai)
            results.append(SchemaDriftService._result(report, event, created, full=True))
        return results

    @staticmethod
    def scan_all(app: FastAPI, db: Session, save: bool = True, use_ai: bool = True) -> dict:
        _, normalized = OpenAPIExtractionService.extracted_paths(app)
        operations = SchemaDriftService.observed_operations(db, list(normalized.keys()))
        results = []
        for route, method in operations:
            try:
                report = SchemaDriftService.analyze(db, normalized, route, method)
                event, created = (None, False)
                if save and report["has_drift"]:
                    event, created = SchemaDriftService.save_drift(db, report, use_ai=use_ai)
                results.append(SchemaDriftService._result(report, event, created, full=False))
            except Exception as exc:  # keep scanning the remaining endpoints
                logger.exception("Drift scan failed for %s %s", method, route)
                db.rollback()
                results.append({"endpoint": route, "method": method, "status": "error", "error": str(exc)})

        with_drift = [r for r in results if r.get("has_drift")]
        return {
            "scanned": len(results),
            "with_drift": len(with_drift),
            "new_events": sum(1 for r in results if r.get("event_created")),
            "by_severity": {
                s: sum(1 for r in with_drift if r.get("severity") == s) for s in ("high", "medium", "low")
            },
            "results": results,
        }
