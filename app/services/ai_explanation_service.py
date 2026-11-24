"""Explains drift reports in plain language.

Uses Groq (LLaMA 3.1) when GROQ_API_KEY is configured and falls back to a deterministic
rule-based explainer otherwise, or whenever the AI call fails. The system therefore works
fully offline and never blocks drift detection on an external service.
"""
import json
import logging
from typing import Tuple

from app.config import settings
from app.utils.schema_utils import extract_json

logger = logging.getLogger(__name__)

EXPLANATION_KEYS = ("summary", "cause", "impact", "doc_fix", "code_fix", "severity")


class AIClient:
    _client = None

    @classmethod
    def client(cls):
        if cls._client is None:
            from groq import Groq

            cls._client = Groq(api_key=settings.GROQ_API_KEY, timeout=settings.AI_TIMEOUT_SECONDS)
        return cls._client

    @classmethod
    def chat_json(cls, system: str, prompt: str):
        """Ask the model for a JSON object. Returns a dict or None on any failure."""
        if not settings.ai_available:
            return None
        try:
            response = cls.client().chat.completions.create(
                model=settings.AI_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            parsed = extract_json(response.choices[0].message.content)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            logger.exception("AI request failed; falling back to rule-based engine")
            return None


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)]


class AIExplanationService:
    SYSTEM_PROMPT = (
        "You are a senior API architect. You analyse schema drift between an OpenAPI contract "
        "and real traffic and answer ONLY with a compact JSON object."
    )

    @staticmethod
    def explain(endpoint: str, method: str, report: dict, use_ai: bool = True) -> Tuple[dict, str]:
        """Return (explanation dict, provider) where provider is 'groq' or 'rule-based'."""
        fallback = AIExplanationService.rule_based(endpoint, method, report)
        if not use_ai or not settings.ai_available:
            return fallback, "rule-based"

        issues = [
            {k: i.get(k) for k in ("location", "category", "field", "severity", "expected", "observed")}
            for i in report.get("issues", [])[:40]
        ]
        prompt = (
            f"Endpoint: {method} {endpoint}\n"
            f"Samples analysed: {json.dumps(report.get('sample_size', {}))}\n"
            f"Detected issues (JSON): {json.dumps(issues)}\n\n"
            "Return a JSON object with exactly these keys:\n"
            '  "summary": one or two sentences,\n'
            '  "cause": the most likely root cause,\n'
            '  "impact": the impact on API consumers,\n'
            '  "doc_fix": array of concrete OpenAPI documentation changes,\n'
            '  "code_fix": array of concrete backend (FastAPI / Pydantic) changes,\n'
            '  "severity": one of "low", "medium", "high".\n'
            "Keep it short, accurate and actionable."
        )
        data = AIClient.chat_json(AIExplanationService.SYSTEM_PROMPT, prompt)
        if not data:
            return fallback, "rule-based"

        result = {
            "summary": str(data.get("summary") or fallback["summary"]),
            "cause": str(data.get("cause") or fallback["cause"]),
            "impact": str(data.get("impact") or fallback["impact"]),
            "doc_fix": _as_list(data.get("doc_fix")) or fallback["doc_fix"],
            "code_fix": _as_list(data.get("code_fix")) or fallback["code_fix"],
            "severity": str(data.get("severity") or "").lower() or fallback["severity"],
        }
        if result["severity"] not in {"low", "medium", "high"}:
            result["severity"] = fallback["severity"]
        return result, "groq"

    # ------------------------------------------------------------------ rule-based engine
    @staticmethod
    def rule_based(endpoint: str, method: str, report: dict) -> dict:
        issues = report.get("issues", [])
        severity = report.get("severity") or "low"
        by_cat = {}
        for issue in issues:
            by_cat.setdefault((issue["location"], issue["category"]), []).append(issue.get("field"))

        def fields(location, category):
            return [f for f in by_cat.get((location, category), []) if f]

        def fmt(names):
            names = list(dict.fromkeys(names))
            shown = ", ".join(f"'{n}'" for n in names[:6])
            return shown + (f" and {len(names) - 6} more" if len(names) > 6 else "")

        counts = {}
        for issue in issues:
            counts[issue["category"]] = counts.get(issue["category"], 0) + 1
        def plural(label, n):
            if n == 1:
                return label
            return label + ("es" if label.endswith(("h", "s")) else "s")

        breakdown = ", ".join(f"{n} {plural(c.replace('_', ' '), n)}" for c, n in sorted(counts.items()))
        summary = f"{len(issues)} contract issue(s) detected on {method} {endpoint}: {breakdown}."

        causes, impacts, doc_fix, code_fix = [], [], [], []

        undocumented_resp = fields("response", "undocumented_field")
        if undocumented_resp:
            causes.append(
                "The handler returns fields that are not declared in its response model — typically a "
                "handler that returns a raw dict/JSONResponse (bypassing `response_model`) or a model "
                "that changed without the docs being regenerated."
            )
            impacts.append("Consumers relying on the spec do not know these fields exist; generated SDKs drop them.")
            doc_fix.append(f"Document response field(s) {fmt(undocumented_resp)} in the response schema.")
            code_fix.append(
                f"Add {fmt(undocumented_resp)} to the response model, or stop returning them if they are internal."
            )

        type_resp = fields("response", "type_mismatch")
        if type_resp:
            causes.append(
                "Runtime values have a different JSON type than documented (e.g. numbers serialised as "
                "strings, legacy rows, or manual serialisation)."
            )
            impacts.append("Strictly-typed clients fail to deserialise these responses.")
            doc_fix.append(f"Fix the documented type of {fmt(type_resp)} if the runtime behaviour is intended.")
            code_fix.append(
                f"Coerce {fmt(type_resp)} to the documented type before returning, or enforce it via `response_model`."
            )

        null_resp = fields("response", "nullable_mismatch")
        if null_resp:
            causes.append("Some records contain null values for fields documented as non-nullable.")
            impacts.append("Clients that do not expect null can crash (null pointer / undefined access).")
            doc_fix.append(f"Mark {fmt(null_resp)} as nullable (`Optional[...]`) or document defaults.")
            code_fix.append(f"Backfill or default null values for {fmt(null_resp)}.")

        missing_resp = fields("response", "missing_field") + fields("response", "required_mismatch")
        if missing_resp:
            causes.append("Documented response fields are omitted from some or all responses.")
            impacts.append("Clients reading these fields receive undefined values.")
            doc_fix.append(f"Mark {fmt(missing_resp)} as optional or remove them if they no longer exist.")
            code_fix.append(f"Always include {fmt(missing_resp)} in responses (use defaults where needed).")

        undocumented_req = fields("request", "undocumented_field")
        if undocumented_req:
            causes.append("Clients send fields the API does not declare; Pydantic silently ignores them.")
            impacts.append("Client intent is lost silently — data the client believes was saved is discarded.")
            doc_fix.append(f"Decide whether {fmt(undocumented_req)} should be accepted and document them.")
            code_fix.append(
                f"Add {fmt(undocumented_req)} to the request model, or set `model_config = ConfigDict(extra='forbid')` "
                "to reject unknown fields explicitly."
            )

        req_contract = (
            fields("request", "required_mismatch")
            + fields("request", "missing_field")
            + fields("request", "type_mismatch")
            + fields("request", "nullable_mismatch")
        )
        if req_contract:
            causes.append("Clients send request bodies that violate the documented request schema.")
            impacts.append("Those requests are rejected with 422 validation errors.")
            doc_fix.append(f"Clarify the requirements for {fmt(req_contract)} in the request schema and examples.")
            code_fix.append(
                f"Relax the validation of {fmt(req_contract)} (defaults / Optional) if clients legitimately omit them."
            )

        for category, text in (
            ("undocumented_endpoint", "The route is reachable but excluded from the OpenAPI spec."),
            ("undocumented_response", "The response has no documented schema (missing `response_model`)."),
            ("undocumented_request", "The request body has no documented schema."),
        ):
            if counts.get(category):
                causes.append(text)
                doc_fix.append("Add an explicit Pydantic model so the shape is documented.")
                code_fix.append("Declare `response_model=` / typed body parameters on the route.")
                impacts.append("Consumers have no machine-readable contract for this payload.")

        if not causes:
            causes.append("The runtime behaviour differs from the documented schema.")
            impacts.append("Documentation and implementation are out of sync.")

        return {
            "summary": summary,
            "cause": " ".join(dict.fromkeys(causes)),
            "impact": " ".join(dict.fromkeys(impacts)),
            "doc_fix": list(dict.fromkeys(doc_fix)) or ["Regenerate the OpenAPI spec from the current models."],
            "code_fix": list(dict.fromkeys(code_fix)) or ["Align the Pydantic models with real behaviour."],
            "severity": severity,
        }

    # ------------------------------------------------------------------ legacy API
    @staticmethod
    def explain_drift(endpoint, method, drift_report) -> str:
        """Backward compatible wrapper that returns the explanation as a JSON string."""
        report = drift_report if "issues" in (drift_report or {}) else {"issues": [], "severity": "low"}
        explanation, _ = AIExplanationService.explain(endpoint, method, report)
        return json.dumps(explanation)
