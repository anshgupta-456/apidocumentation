"""End-to-end tests through the FastAPI app (SQLite, rule-based explanations)."""
import json
import os

from app.database.models import ApiLog
from app.database.session import SessionLocal


def _logs():
    db = SessionLocal()
    try:
        return db.query(ApiLog).all()
    finally:
        db.close()


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["ai"]["provider"] == "rule-based"


def test_demo_user_crud_and_404(client):
    created = client.post("/api/users", json={"name": "Ada", "age": 36})
    assert created.status_code == 201
    user_id = created.json()["id"]
    assert client.get(f"/api/users/{user_id}").json()["name"] == "Ada"
    assert client.put(f"/api/users/{user_id}", json={"age": 37}).json()["age"] == 37
    assert len(client.get("/api/users").json()) == 1
    assert client.get("/api/users/999").status_code == 404  # used to crash with a 500
    assert client.delete(f"/api/users/{user_id}").status_code == 204


def test_middleware_logs_route_template_and_skips_admin_routes(client):
    client.post("/api/users", json={"name": "Ada"})
    client.get("/api/users/1")
    client.get("/health")
    client.get("/ui")

    logs = _logs()
    assert {(l.method, l.route_path) for l in logs} == {("POST", "/api/users"), ("GET", "/api/users/{user_id}")}
    post = next(l for l in logs if l.method == "POST")
    assert post.request_json == {"name": "Ada"}
    assert post.response_json["name"] == "Ada"
    assert post.status_code == 201


def test_clean_endpoint_has_no_drift(client):
    for i in range(5):
        client.post("/api/users", json={"name": f"user{i}", "age": 20 + i})
    body = client.get("/detect-drift/api/users", params={"method": "POST"}).json()
    result = body["results"][0]
    assert result["status"] == "clean"
    assert not result["has_drift"] and result["event_id"] is None


def test_products_drift_is_detected_saved_and_deduplicated(client):
    for product_id in (1, 2, 3, 4):
        client.get(f"/api/products/{product_id}")

    first = client.get("/detect-drift/api/products/{product_id}", params={"method": "GET"}).json()["results"][0]
    assert first["has_drift"] and first["severity"] == "high" and first["event_created"]
    found = {(i["category"], i["field"]) for i in first["issues"]}
    assert ("undocumented_field", "discount_percent") in found
    assert ("undocumented_field", "supplier") in found  # nested children are not repeated
    assert ("undocumented_field", "supplier.name") not in found
    assert ("type_mismatch", "price") in found
    assert ("nullable_mismatch", "price") in found

    again = client.get("/detect-drift/api/products/1", params={"method": "GET"}).json()["results"][0]
    assert again["event_id"] == first["event_id"] and not again["event_created"]

    event = client.get(f"/drift-events/{first['event_id']}").json()
    assert event["occurrences"] == 2
    assert event["ai_provider"] == "rule-based"
    assert event["ai_explanation"]["summary"]
    assert "discount_percent" in event["backend_patch"]


def test_request_drift_from_misbehaving_clients(client):
    client.post("/api/users", json={"name": "Ada", "nickname": "A"})
    client.post("/api/users", json={"age": 30})  # missing required name -> 422
    result = client.get("/detect-drift/api/users", params={"method": "POST"}).json()["results"][0]
    found = {(i["location"], i["category"], i["field"]) for i in result["issues"]}
    assert ("request", "undocumented_field", "nickname") in found
    assert ("request", "required_mismatch", "name") in found
    # error responses ({"detail": ...}) must not be treated as response drift
    assert not any(i["location"] == "response" for i in result["issues"])


def test_scan_all_and_event_lifecycle(client):
    client.get("/api/products")
    client.post("/api/users", json={"name": "Ada"})
    scan = client.post("/drift/scan", json={"save": True}).json()
    assert scan["scanned"] == 2 and scan["with_drift"] == 1 and scan["new_events"] == 1

    listing = client.get("/drift-events", params={"status": "active"}).json()
    assert listing["total"] == 1
    event_id = listing["items"][0]["id"]

    updated = client.patch(f"/drift-events/{event_id}", json={"status": "resolved", "notes": "fixed in v2"}).json()
    assert updated["status"] == "resolved" and updated["resolved_at"] and updated["notes"] == "fixed in v2"
    assert client.get("/drift-events", params={"status": "active"}).json()["total"] == 0

    csv_body = client.get("/drift-events/export", params={"format": "csv"}).text
    assert "/api/products" in csv_body.splitlines()[1]
    assert client.patch(f"/drift-events/{event_id}", json={"status": "bogus"}).status_code == 422

    assert client.delete(f"/drift-events/{event_id}").status_code == 204
    assert client.get(f"/drift-events/{event_id}").status_code == 404


def test_patch_apply_writes_generated_spec(client):
    client.get("/api/products/3")
    event_id = client.get("/detect-drift/api/products/3", params={"method": "GET"}).json()["results"][0]["event_id"]

    result = client.post("/patch/apply", params={"event_id": event_id}).json()
    assert result["results"]["openapi"]["changed_operations"] == ["GET /api/products/{product_id}"]

    path = os.environ["GENERATED_SPEC_PATH"]
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    schema = spec["paths"]["/api/products/{product_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert "discount_percent" in schema["properties"]
    assert client.get("/patch/generated-spec").status_code == 200

    # legacy query style still works
    legacy = client.post("/patch/apply", params={"endpoint": "/api/products/{product_id}", "method": "GET"})
    assert legacy.status_code == 200


def test_openapi_versioning_and_diff(client):
    first = client.get("/extract-openapi", params={"include_spec": False}).json()
    assert first["changed"] is True
    second = client.get("/extract-openapi").json()
    assert second["changed"] is False and "raw" in second

    specs = client.get("/openapi-specs").json()
    assert len(specs) == 1 and specs[0]["endpoint_count"] > 5
    diff = client.get("/openapi-specs/diff").json()
    assert diff["diff"]["summary"]["identical"] is True
    assert client.get(f"/openapi-specs/{specs[0]['id']}/download").status_code == 200


def test_stats_endpoints_and_logs(client):
    client.post("/api/users", json={"name": "Ada"})
    client.get("/api/users/42")  # 404
    stats = client.get("/stats").json()
    assert stats["requests"]["total"] == 2 and stats["requests"]["errors"] == 1
    assert stats["endpoints"]["documented"] >= 7

    endpoints = {(e["method"], e["endpoint"]): e for e in client.get("/endpoints").json()}
    assert endpoints[("GET", "/api/users/{user_id}")]["error_rate"] == 100.0
    assert endpoints[("GET", "/api/products")]["requests"] == 0

    logs = client.get("/api-logs", params={"status": "error"}).json()
    assert logs["total"] == 1 and logs["items"][0]["status_code"] == 404
    assert client.delete("/api-logs").json()["deleted"] == 2


def test_demo_traffic_generator(client):
    body = client.post("/demo/traffic", params={"requests": 25}).json()
    assert body["sent"] == 25
    assert len(_logs()) == 25


def test_ui_pages_render(client):
    client.post("/demo/traffic", params={"requests": 40})
    client.get("/extract-openapi")
    scan = client.post("/drift/scan", json={}).json()
    event_id = next(r["event_id"] for r in scan["results"] if r.get("event_id"))
    spec_id = client.get("/openapi-specs").json()[0]["id"]

    for url in [
        "/ui",
        "/ui/endpoints",
        "/ui/endpoints?all=true",
        "/ui/drifts",
        "/ui/drifts?status=active&severity=high",
        f"/ui/drift/{event_id}",
        "/ui/openapi",
        f"/ui/openapi/{spec_id}",
        "/ui/openapi/diff",
        "/ui/logs",
        "/ui/logs?status=error",
    ]:
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert "API Contract" in resp.text

    assert client.get("/ui/drift/not-a-uuid").status_code == 404
    assert client.get("/").url.path == "/ui"
