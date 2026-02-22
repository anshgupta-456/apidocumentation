# from datetime import datetime
# from sqlalchemy.orm import Session
# from app.database.models import DriftEvents
# from app.database.session import SessionLocal

# class SchemaDriftService:

#     @staticmethod
    
#     def compare(expected: dict, runtime: dict) -> dict:
#         drift = {
#             "missing_in_runtime": [],
#             "missing_in_openapi": [],
#             "type_mismatches": [],
#             "nullable_mismatches": [],
#             "required_mismatches": []
#         }

#         # --- Fix: Normalize runtime to include "required" ---
#         for field, r in runtime.items():
#             # runtime has no "required", so we compute it
#             r["required"] = r.get("presence_percent", 0) == 100.0

#         # --- Check fields expected but missing in runtime ---
#         for field in expected:
#             if field not in runtime:
#                 drift["missing_in_runtime"].append(field)

#         # --- Check fields present in runtime but not in OpenAPI ---
#         for field in runtime:
#             if field not in expected:
#                 drift["missing_in_openapi"].append(field)

#         # --- Compare each field ---
#         for field in expected:
#             if field not in runtime:
#                 continue

#             o = expected[field]
#             r = runtime[field]

#             # type mismatch
#             if o["type"] not in r["types"]:
#                 drift["type_mismatches"].append({
#                     "field": field,
#                     "expected": o["type"],
#                     "runtime": r["types"]
#                 })

#             # nullable mismatch
#             if o["nullable"] != r["nullable"]:
#                 drift["nullable_mismatches"].append({
#                     "field": field,
#                     "expected": o["nullable"],
#                     "runtime": r["nullable"]
#                 })

#             # required mismatch (fixed)
#             if o["required"] != r["required"]:
#                 drift["required_mismatches"].append({
#                     "field": field,
#                     "expected": o["required"],
#                     "runtime": r["required"]
#                 })

#         return drift
#     @staticmethod
#     def save_drift(endpoint:str, drift_json: dict, severity="medium", ai_message=""):
#         db: Session = SessionLocal()
#         entry = DriftEvents(
#             endpoint=endpoint,
#             severity=severity,
#             drift_detail=drift_json,
#             ai_explanation=ai_message,
#             detected_at=datetime.utcnow()
#         )
#         db.add(entry)
#         db.commit()
#         db.close()
#         return {"status": "saved", "endpoint": endpoint}

from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import DriftEvents
from app.database.session import SessionLocal
from app.services.ai_explanation_service import AIExplanationService

class SchemaDriftService:

    @staticmethod
    def compare(expected: dict, runtime: dict) -> dict:
        drift = {
            "missing_in_runtime": [],
            "missing_in_openapi": [],
            "type_mismatches": [],
            "nullable_mismatches": [],
            "required_mismatches": []
        }

        # Normalize runtime -> add required field logic
        for field, r in runtime.items():
            r["required"] = r.get("presence_percent", 0) == 100.0

        # missing fields (expected but not in runtime)
        for field in expected:
            if field not in runtime:
                drift["missing_in_runtime"].append(field)

        # extra fields (runtime but not in OpenAPI)
        for field in runtime:
            if field not in expected:
                drift["missing_in_openapi"].append(field)

        # Compare attributes
        for field in expected:
            if field not in runtime:
                continue

            o = expected[field]
            r = runtime[field]

            if o["type"] not in r["types"]:
                drift["type_mismatches"].append({
                    "field": field,
                    "expected": o["type"],
                    "runtime": r["types"]
                })

            if o["nullable"] != r["nullable"]:
                drift["nullable_mismatches"].append({
                    "field": field,
                    "expected": o["nullable"],
                    "runtime": r["nullable"]
                })

            if o["required"] != r["required"]:
                drift["required_mismatches"].append({
                    "field": field,
                    "expected": o["required"],
                    "runtime": r["required"]
                })

        return drift


    @staticmethod
    def save_drift(endpoint: str, method: str, drift_json: dict):
        db: Session = SessionLocal()

        # --- Severity classification ---
        if drift_json["type_mismatches"] or drift_json["required_mismatches"]:
            severity = "high"
        elif drift_json["missing_in_openapi"]:
            severity = "medium"
        else:
            severity = "low"

        # --- Generate AI explanation ---
        ai_message = AIExplanationService.explain_drift(
            endpoint,
            method,
            drift_json
        )

        # --- Insert into DB ---
        entry = DriftEvents(
            endpoint=endpoint,
            severity=severity,
            drift_detail=drift_json,
            ai_explanation=ai_message,
            detected_at=datetime.utcnow()
        )

        db.add(entry)
        db.commit()
        db.close()

        return {"status": "saved", "endpoint": endpoint, "severity": severity}