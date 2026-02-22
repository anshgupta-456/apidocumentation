import json
import hashlib
from fastapi import FastAPI
from sqlalchemy.orm import Session
from app.database.models import OpenAPISpec
from app.database.session import SessionLocal
from datetime import datetime

class OpenAPIExtractionnService:
    @staticmethod
    def compute_hash(spec: dict) -> str:
        # HAsh the entire openapi spec for versioning
        return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    @staticmethod
    def normalize_schema(schema: dict) ->dict:
        # convert the openapi schema into comparable format
        normalized = {}
        if "properties" not in schema:
            return normalized
        properties = schema.get("properties", {})
        required_fields = schema.get("required", [])

        for field_name, field_info in properties.items():
            normalized[field_name] = {
                "type": field_info.get("type", "object"),
                "nullable": field_info.get("nullable", False),
                "required": field_name in required_fields
            }
        return normalized
    @staticmethod
    def extracted_paths(app: FastAPI) -> dict:
        # Extract and normalize openapi paths
        spec = app.openapi()
        paths = spec.get("paths", {})

        normalized_paths = {}

        for path, methods in paths.items():
            normalized_paths[path] = {}
            for method, details in methods.items():
                responses = details.get("responses",{})

                    #extract 200 response body schema
                if "200" in responses:
                    content = (
                        responses["200"]
                        .get("content", {})
                        .get("application/json", {})
                        .get("schema", {})
                    )
                normalized_paths[path][method.upper()] = OpenAPIExtractionnService.normalize_schema(content or {})
        return spec, normalized_paths
    @staticmethod
    def save_to_db(spec: dict, normalized_paths: dict):
        #save the new openapo version
        db: Session = SessionLocal()
        version_hash = OpenAPIExtractionnService.compute_hash(spec)

        entry = OpenAPISpec(
            version_hash = version_hash,
            spec_json = spec,
            normalized_paths = normalized_paths,
            extracted_at = datetime.now()
        )

        db.add(entry)
        db.commit()
        db.close()
    @staticmethod
    def run_extraction(app: FastAPI):
        # function to extract and save openapi
        spec, normalized_paths = OpenAPIExtractionnService.extracted_paths(app)
        OpenAPIExtractionnService.save_to_db(spec, normalized_paths)
        return normalized_paths