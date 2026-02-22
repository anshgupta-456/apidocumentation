import json
import hashlib
from fastapi import FastAPI
from sqlalchemy.orm import Session
from app.database.models import OpenAPISpec
from app.database.session import SessionLocal
from datetime import datetime


class OpenAPIExtractionService:

    @staticmethod
    def compute_hash(spec: dict) -> str:
        """Hash the full OpenAPI spec for versioning."""
        return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def normalize_schema(schema: dict) -> dict:
        """Convert OpenAPI schema into comparable normalized format."""
        normalized = {}

        if "properties" not in schema:
            return normalized

        properties = schema["properties"]
        required_fields = schema.get("required", [])

        for field, info in properties.items():
            normalized[field] = {
                "type": info.get("type", "object"),
                "nullable": info.get("nullable", False),
                "required": field in required_fields
            }

        return normalized

    @staticmethod
    def resolve_schema(spec: dict, schema: dict) -> dict:
        """Resolve $ref from components."""
        if "$ref" not in schema:
            return schema

        ref_path = schema["$ref"]  # e.g., "#/components/schemas/UserResponse"
        _, _, path = ref_path.partition("#/")

        parts = path.split("/")  # ["components", "schemas", "UserResponse"]

        resolved = spec
        for p in parts:
            resolved = resolved.get(p, {})

        return resolved

    @staticmethod
    def extracted_paths(app: FastAPI) -> dict:
        """Extract and normalize OpenAPI paths."""
        spec = app.openapi()
        paths = spec.get("paths", {})

        normalized_paths = {}

        for path, methods in paths.items():
            normalized_paths[path] = {}

            for method, details in methods.items():
                responses = details.get("responses", {})

                content = {}
                if "200" in responses:
                    schema = (
                        responses["200"]
                        .get("content", {})
                        .get("application/json", {})
                        .get("schema", {})
                    )

                    # NEW IMPORTANT FIX: resolve $ref schemas
                    schema = OpenAPIExtractionService.resolve_schema(spec, schema)

                    content = OpenAPIExtractionService.normalize_schema(schema)

                normalized_paths[path][method.upper()] = content

        return spec, normalized_paths

    @staticmethod
    def save_to_db(spec: dict, normalized_paths: dict):
        """Save extracted OpenAPI spec to database."""
        db: Session = SessionLocal()

        version_hash = OpenAPIExtractionService.compute_hash(spec)

        entry = OpenAPISpec(
            version_hash=version_hash,
            spec_json=spec,
            normalized_paths=normalized_paths,
            extracted_at=datetime.now()
        )

        db.add(entry)
        db.commit()
        db.close()

    @staticmethod
    def run_extraction(app: FastAPI):
        """Run OpenAPI extraction and save it."""
        spec, normalized_paths = OpenAPIExtractionService.extracted_paths(app)
        OpenAPIExtractionService.save_to_db(spec, normalized_paths)
        return normalized_paths