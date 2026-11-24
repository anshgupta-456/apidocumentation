"""Unit tests for inference, OpenAPI normalization, drift comparison and patch generation."""
from app.services.drift_detection_service import SchemaDriftService, normalize_drift_detail
from app.services.openapi_extraction_service import OpenAPIExtractionService
from app.services.patch_generation_service import PatchGenerationService
from app.services.schema_inference_service import SchemaInferenceService
from app.services.spec_diff_service import SpecDiffService
from app.utils.schema_utils import extract_json, match_template, runtime_to_json_schema


def test_inference_handles_nested_objects_arrays_and_presence():
    bodies = [
        {"id": 1, "name": "a", "address": {"city": "X", "zip": None}, "orders": [{"total": 1.5}, {"total": 2}]},
        {"id": 2, "name": None, "address": {"city": "Y"}, "orders": []},
    ]
    schema = SchemaInferenceService.build_schema_from_bodies(bodies)

    assert schema["id"]["types"] == ["integer"] and schema["id"]["required"]
    assert schema["name"]["nullable"] and schema["name"]["types"] == ["string"]
    assert schema["address.city"]["required"]  # present whenever the parent is present
    assert schema["address.zip"]["presence_percent"] == 50.0 and not schema["address.zip"]["required"]
    assert set(schema["orders[].total"]["types"]) == {"integer", "number"}


def test_inference_of_top_level_arrays():
    schema = SchemaInferenceService.build_schema_from_bodies([[{"id": 1}, {"id": 2, "x": "y"}]])
    assert schema["[].id"]["required"]
    assert schema["[].x"]["presence_percent"] == 50.0


def test_openapi_flatten_resolves_refs_anyof_and_arrays():
    spec = {
        "components": {
            "schemas": {
                "Address": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
                "User": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "integer"},
                        "age": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                        "address": {"anyOf": [{"$ref": "#/components/schemas/Address"}, {"type": "null"}]},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "meta": {"type": "object", "additionalProperties": True},
                    },
                },
            }
        }
    }
    fields = OpenAPIExtractionService.flatten(spec, {"$ref": "#/components/schemas/User"})
    assert fields["id"] == {"type": "integer", "nullable": False, "required": True}
    assert fields["age"]["nullable"] and fields["age"]["type"] == "integer"
    assert fields["address"]["nullable"] and fields["address.city"]["required"]
    assert fields["tags"]["item_type"] == "string"
    assert fields["meta"]["free_form"]

    array_fields = OpenAPIExtractionService.flatten(spec, {"type": "array", "items": {"$ref": "#/components/schemas/User"}})
    assert "[].id" in array_fields and "[].address.city" in array_fields


def test_compare_reports_violations_but_not_allowed_behaviour():
    expected = {
        "id": {"type": "integer", "nullable": False, "required": True},
        "price": {"type": "number", "nullable": False, "required": True},
        "note": {"type": "string", "nullable": True, "required": False},
        "meta": {"type": "object", "nullable": False, "required": False, "free_form": True},
    }
    runtime = SchemaInferenceService.build_schema_from_bodies(
        [
            {"id": 1, "price": 10, "note": "x", "extra": True, "meta": {"anything": 1}},
            {"id": 2, "price": "9.99", "note": "y", "extra": False, "meta": {}},
            {"id": 3, "price": None, "note": "z", "extra": True, "meta": {}},
        ]
    )
    drift = SchemaDriftService.compare(expected, runtime, "response")

    assert drift["missing_in_openapi"] == ["extra"]  # meta.* is free-form -> ignored
    assert [m["field"] for m in drift["type_mismatches"]] == ["price"]  # integer is fine for number
    assert [m["field"] for m in drift["nullable_mismatches"]] == ["price"]
    # 'note' is optional+nullable but always present & never null: allowed, not drift
    assert not drift["required_mismatches"]

    issues = SchemaDriftService.build_issues("response", drift, expected, runtime)
    assert SchemaDriftService.overall_severity(issues) == "high"
    assert {i["category"] for i in issues} == {"undocumented_field", "type_mismatch", "nullable_mismatch"}


def test_request_compare_ignores_optional_fields_never_sent():
    expected = {
        "name": {"type": "string", "nullable": False, "required": True},
        "email": {"type": "string", "nullable": True, "required": False},
    }
    runtime = SchemaInferenceService.build_schema_from_bodies([{"name": "a", "nickname": "x"}, {"age": 3}])
    drift = SchemaDriftService.compare(expected, runtime, "request")
    assert drift["missing_in_runtime"] == []
    assert drift["required_mismatches"][0]["field"] == "name"
    assert set(drift["missing_in_openapi"]) == {"nickname", "age"}


def test_legacy_drift_detail_is_normalized():
    legacy = {
        "missing_in_runtime": ["id"],
        "missing_in_openapi": ["detail"],
        "type_mismatches": [],
        "nullable_mismatches": [],
        "required_mismatches": [{"field": "name", "expected": True, "runtime": False}],
    }
    detail = normalize_drift_detail(legacy)
    assert detail["version"] == 1
    assert {i["field"] for i in detail["issues"]} == {"id", "detail", "name"}


def test_runtime_to_json_schema_and_generated_models_compile():
    runtime = SchemaInferenceService.build_schema_from_bodies(
        [
            {"id": 1, "price": "1.0", "supplier": {"name": "A"}, "tags": ["x"], "class": "k"},
            {"id": 2, "price": None, "supplier": {"name": "B"}, "tags": [], "class": "k"},
        ]
    )
    schema = runtime_to_json_schema(runtime)
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"class", "id", "price", "supplier", "tags"}
    assert schema["properties"]["price"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert schema["properties"]["supplier"]["properties"]["name"] == {"type": "string"}
    assert schema["properties"]["tags"]["items"] == {"type": "string"}

    report = {
        "endpoint": "/api/products/{product_id}",
        "method": "GET",
        "response_status": "200",
        "issues": [{"location": "response", "category": "undocumented_field", "field": "class",
                    "severity": "medium", "message": "m"}],
        "runtime_schema": {"response": runtime, "request": {}},
        "expected_schema": {"response": {}, "request": {}},
        "sample_size": {"response": 2, "request": 0},
    }
    patches = PatchGenerationService.generate(report)
    op = patches["openapi_patch"]["paths"]["/api/products/{product_id}"]["get"]
    assert "200" in op["responses"]

    namespace: dict = {}
    exec(patches["backend_patch"], namespace)  # generated code must be valid Python
    model = namespace["ProductsGetResponse"]
    instance = model.model_validate({"id": 1, "price": None, "supplier": {"name": "A"}, "tags": [], "class": "k"})
    assert instance.supplier.name == "A"
    assert instance.class_ == "k"


def test_spec_diff_flags_breaking_changes():
    def spec(props, required):
        return {
            "paths": {
                "/api/x": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object", "properties": props, "required": required}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

    old = spec({"a": {"type": "string"}, "b": {"type": "integer"}}, ["a"])
    new = spec({"a": {"type": "integer"}, "c": {"type": "string"}}, ["a"])
    diff = SpecDiffService.diff(old, new)
    changes = {(c["field"], c["change"]): c["breaking"] for c in diff["changed_endpoints"][0]["changes"]}
    assert changes[("a", "type_changed")] is True
    assert changes[("b", "removed")] is True
    assert changes[("c", "added")] is False
    assert diff["summary"]["breaking_changes"] == 2


def test_helpers():
    assert match_template("/api/users/42", ["/api/users", "/api/users/{user_id}"]) == "/api/users/{user_id}"
    assert match_template("/api/other", ["/api/users/{user_id}"]) is None
    text = 'Sure! ```json\n{"openapi_patch": {"paths": {}}, "backend_patch": "x"}\n``` hope it helps'
    assert extract_json(text)["backend_patch"] == "x"
