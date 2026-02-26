import json
import os

from fastapi import openapi

class OpenAPIPatchService:
    OPENAPI_PATH: "openapi.json"
    GENERATED_PATH: "openapi.generated.json"

    @staticmethod
    def load_original_spec():
        if not os.path.exists(OpenAPIPatchService.OPENAPI_PATH):
            raise FileNotFoundError(f"Original OpenAPI spec not found at {OpenAPIPatchService.OPENAPI_PATH}")
        with open(OpenAPIPatchService.OPENAPI_PATH, "r") as f:
            return json.load(f)
        @staticmethod
        def save_generated_spec(updated_spec: dict):
            with open(OpenAPIPatchService.GENERATED_PATH, "w") as f:
                json.dump(updated_spec, f, indent=2)
        @staticmethod
        def apply_patch(patch: dict):
            """
            patch = {
                "paths": {
                    "/api/users": {
                        "post": {
                            "requestBody": {
                                "required": ["id","name"]
                                }
                                }
                                }
                                }
            """
            spec = OpenAPIPatchService.load_original_spec()

            for path, methods in patch.get("paths", {}).items():
                if path not in spec["paths"]:
                    spec["paths"][path] = {}
                for method, content in methods.items():
                    if method not in spec["paths"][path]:
                        spec["paths"][path][method] = {}
                    for key,value in content.items():
                        spec["paths"][path][method][key] = value
            OpenAPIPatchService.save_generated_spec(spec)
            return{
                "message": "Patch applied successfully",
                "generated_spec_path": OpenAPIPatchService.GENERATED_PATH
            }