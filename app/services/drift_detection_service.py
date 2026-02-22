from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import DriftEvents
from app.database.session import SessionLocal

class SchemaDriftService:

    @staticmethod
    def compare(openapi_schema: dict, runtime_schema: dict) -> dict:
        drift = {
            "missing_in_runtime":[],
            "missing_in_openapi": [],
            "type_mismatches": [],
            "nullable_mismatches": [],
            "required_mismatches": []
        }
        openapi_fields = set(openapi_schema.keys())
        runtime_fields = set(runtime_schema.keys())

        #missing fields in runtime
        for field in openapi_fields - runtime_fields:
            drift["missing_in_runtime"].append(field)
        #new undocumented fields in runtime
        for field in runtime_fields - openapi_fields:
            drift["missing_in_openapi"].append(field)
        # compare shared fields
        for field in openapi_fields & runtime_fields:
            o = openapi_schema[field]
            r = runtime_schema[field]

            if o["type"] != r["types"][0]:
                drift["type_mismatches"].append({
                    "field": field,
                    "openapi": o["type"],
                    "runtime": r["types"]
                })
            if o["nullable"] != r["nullable"]:
                drift["nullable_mismatches"].append({
                    "field": field,
                    "openapi": o["nullable"],
                    "runtime": r["nullable"]
                })
            if o["required"] != r["required"]:
                drift["required_mismatches"].append({
                    "field": field,
                    "openapi": True,
                    "runtime_presence": r["presence_percent"]
                })
        return drift
    @staticmethod
    def save_drift(endpoint:str, drift_json: dict, severity="medium", ai_message=""):
        db: Session = SessionLocal()
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
        return {"status": "saved", "endpoint": endpoint}