import json
from typing import Any, Dict, List
from sqlalchemy.orm import Session
from app.database.models import ApiLog, InfererredSchema
from app.database.session import SessionLocal
from datetime import datetime

class SchemaInferenceService:
    @staticmethod
    def infer_type(value:Any)-> str:
        # infer the json data type of a value
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "unknown"
    @staticmethod
    def merge_field_stats(existing: Dict, new: Dict) -> Dict:
        # Merge field statistics from multiple samples
        existing["count"] +=new["count"]
        # merge type frequencies
        for t,ct in new["types"].items():
            existing["types"][t] = existing["types"].get(t, 0) + ct
        existiing["null_count"] += new["null_count"]
        return existing
    @staticmethod
    def build_schema(logs: List[ApiLog]) -> Dict:
        # BUild aggregated runttime schema fora set of logs
        field_stats = {} 
        total_samples = len(logs)

        for log in logs:
            response = log.response_json
            if not isinstance(response, dict):
                continue
            for field, value in response.items():
                inferred_type = SchemaInferenceService.infer_type(value)

                new_stats = {
                    "count": 1,
                    "types": {inferred_type: 1},
                    "null_count": 1 if value is None else 0
                }
                if field not in field_stats:
                    field_stats[field] = new_stats
                else:
                    field_stats[field] = SchemaInferenceService.merge_field_stats(field_stats[field], new_stats)
        final_schema = {}

        for field, stats in field_stats.items():
            presence_pct = (stats["count"] / total_samples) * 100
            null_pct = (stats["null_count"] / total_samples) * 100

            final_schema[field] = {
                "types": list(stats["types"].keys()),
                "presence_pct": round(presence_pct, 2),
                "nullable": null_pct>0
            }
        return final_schema
    @staticmethod
    def compute_hash(schema_json: Dict)-> str:
        # compute hash of the schema of versioning
        encoded = json.dumps(schema_json, sort_keys= True).encoded()
        return hashlib.sha256(encoded).hexdigest()
    @staticmethod
    def run_inference(endpoint:str, method:str) -> Dict:
        # Main function to infer schema for an endpoint
        db: Session = SessionLocal()
        logs=(
            db.query(ApiLog)
            .filter(ApiLog.endpoint == endpoint, ApiLog.method == method)
            .all()
        )
        if not logs:
            print("No Logs found for this route")
            return {}
        
        schema = SchemaInferenceService.build_schema(logs)
        schema_hash = SchemaInferenceService.compute_hash(schema)

        # saveto inferred_schema table
        record = InfererredSchema(
            endpoint=endpoint,
            method=method,
            schema_json=schema,
            sample_size=len(logs),
            schema_hash=schema_hash,
            computed_at=datetime.now()
        )
        db.add(record)
        db.commit()

        db.close()
        return schema