"""Tests for hosting/auth, alerts, retention, redaction, playground, endpoint detail and bulk actions."""
from datetime import timedelta

import pytest

from app.config import _database_url, settings
from app.database.models import ApiLog, utcnow
from app.database.session import SessionLocal
from app.middleware.logging_middleware import redact
from app.services import alert_service
from app.services.job_service import cleanup_logs
from app.services.playground_service import example_from_schema


@pytest.fixture()
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "s3cret-pass")
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "key-123")
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret")


def test_postgres_url_is_normalized(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db")
    assert _database_url() == "postgresql+psycopg2://u:p@host:5432/db"
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db?sslmode=require")
    assert _database_url() == "postgresql+psycopg2://u:p@host/db?sslmode=require"
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@host/db")  # explicit driver is kept
    assert _database_url() == "postgresql+psycopg://u:p@host/db"
    monkeypatch.setenv("DATABASE_URL", "")
    assert _database_url().startswith("sqlite")


def test_auth_protects_dashboard_and_management_api(client, auth_on):
    # public surfaces
    assert client.get("/health").status_code == 200
    assert client.post("/api/users", json={"name": "Ada"}).status_code == 201
    assert client.get("/ui/login").status_code == 200

    # protected surfaces
    assert client.get("/stats").status_code == 401
    assert client.get("/drift-events").status_code == 401
    page = client.get("/ui/drifts", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"].startswith("/ui/login?next=")

    # API key access for scripts
    assert client.get("/stats", headers={"X-API-Key": "key-123"}).status_code == 200
    assert client.get("/stats", headers={"Authorization": "Bearer key-123"}).status_code == 200
    assert client.get("/stats", headers={"X-API-Key": "wrong"}).status_code == 401

    # login flow
    assert client.post("/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    ok = client.post("/auth/login", json={"username": "admin", "password": "s3cret-pass"})
    assert ok.status_code == 200 and "acv_session" in ok.cookies
    assert client.get("/stats").status_code == 200
    assert client.get("/ui/drifts").status_code == 200
    assert client.get("/auth/me").json()["username"] == "admin"
    assert client.get("/ui/login", follow_redirects=False).status_code == 303  # already signed in

    client.post("/auth/logout")
    client.cookies.clear()
    assert client.get("/stats").status_code == 401


def test_tampered_session_cookie_is_rejected(client, auth_on):
    client.post("/auth/login", json={"username": "admin", "password": "s3cret-pass"})
    token = client.cookies.get("acv_session")
    client.cookies.clear()
    client.cookies.set("acv_session", token[:-2] + ("00" if token[-2:] != "00" else "11"))
    assert client.get("/stats").status_code == 401


def test_login_rate_limit(client, auth_on):
    for _ in range(8):
        client.post("/auth/login", json={"username": "admin", "password": "bad"})
    assert client.post("/auth/login", json={"username": "admin", "password": "s3cret-pass"}).status_code == 429
    from app import auth

    auth._attempts.clear()


def test_redaction_preserves_types():
    masked = redact({"user": {"password": "hunter2", "pin_token": 1234, "name": "Ada"}, "items": [{"api_key": "x"}]})
    assert masked["user"]["password"] == "[REDACTED]"
    assert masked["user"]["pin_token"] == 0
    assert masked["user"]["name"] == "Ada"
    assert masked["items"][0]["api_key"] == "[REDACTED]"


def test_sensitive_values_are_never_stored(client):
    client.post("/api/users", json={"name": "Ada", "password": "hunter2"})
    db = SessionLocal()
    try:
        log = db.query(ApiLog).one()
        assert log.request_json["password"] == "[REDACTED]"
    finally:
        db.close()


def test_retention_cleanup(client):
    client.post("/api/users", json={"name": "Ada"})
    db = SessionLocal()
    try:
        db.add(ApiLog(endpoint="/api/users", method="GET", status_code=200, created_at=utcnow() - timedelta(days=90)))
        db.commit()
    finally:
        db.close()
    assert cleanup_logs(30) == 1
    assert client.post("/system/cleanup", params={"days": 30}).json()["deleted"] == 0
    db = SessionLocal()
    try:
        assert db.query(ApiLog).count() == 1
    finally:
        db.close()


def test_alert_sent_for_new_high_severity_drift(client, monkeypatch):
    sent = []

    class FakeResponse:
        status_code = 200
        text = "ok"

    monkeypatch.setattr(settings, "ALERT_WEBHOOK_URL", "https://hooks.example.test/abc")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://validator.example.test")
    monkeypatch.setattr(alert_service.httpx, "post", lambda url, json, timeout: sent.append(json) or FakeResponse())

    class InlineThread:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(alert_service.threading, "Thread", InlineThread)

    client.get("/api/products/3")
    client.get("/detect-drift/api/products/3", params={"method": "GET"})
    assert len(sent) == 1
    assert "HIGH schema drift" in sent[0]["text"]
    assert sent[0]["event"]["url"].startswith("https://validator.example.test/ui/drift/")

    client.get("/detect-drift/api/products/3", params={"method": "GET"})  # same drift -> no new alert
    assert len(sent) == 1
    assert client.post("/alerts/test").json()["ok"] is True


def test_test_alert_without_webhook(client):
    assert client.post("/alerts/test").status_code == 400


def test_stats_ranges_and_timeseries(client):
    client.post("/api/users", json={"name": "Ada"})
    client.get("/api/users/99")
    for key, buckets in (("24h", 24), ("7d", 7), ("30d", 30)):
        stats = client.get("/stats", params={"range": key}).json()
        assert len(stats["traffic"]) == buckets
        assert sum(b["requests"] for b in stats["traffic"]) == 2
        assert stats["requests"]["status_codes"]["2xx"] == 1 and stats["requests"]["status_codes"]["4xx"] == 1
    assert 0 <= stats["health"]["score"] <= 100


def test_endpoint_detail(client):
    for product_id in (1, 3, 4):
        client.get(f"/api/products/{product_id}")
    detail = client.get("/endpoints/detail", params={"path": "/api/products/3", "method": "get"}).json()
    assert detail["endpoint"] == "/api/products/{product_id}"
    assert detail["all_time"]["total"] == 3
    verdicts = {r["field"]: r["verdict"] for r in detail["schemas"]["response"]["rows"]}
    assert verdicts["discount_percent"] == "undocumented"
    assert verdicts["price"] in {"type", "nullable"}
    assert verdicts["name"] == "ok"
    assert verdicts["supplier.name"] == "undocumented-child"
    assert client.get("/endpoints/detail", params={"path": "/nope", "method": "GET"}).status_code == 404


def test_playground_operations_and_examples(client):
    ops = {o["id"]: o for o in client.get("/playground/operations").json()}
    create = ops["POST /api/users"]
    assert create["has_body"] and create["body_example"]["name"] == "Ada Lovelace"
    get_user = ops["GET /api/users/{user_id}"]
    assert get_user["path_params"][0]["name"] == "user_id"
    assert all(o["monitored"] for o in ops.values())
    assert any(not o["monitored"] for o in client.get("/playground/operations", params={"all": True}).json())

    spec = {"components": {"schemas": {"A": {"type": "object", "properties": {"email": {"type": "string"}, "n": {"type": "integer", "minimum": 3}}}}}}
    assert example_from_schema(spec, {"$ref": "#/components/schemas/A"}) == {"email": "user@example.com", "n": 3}


def test_bulk_update_and_delete(client):
    client.get("/api/products")
    client.get("/api/products/3")
    client.post("/drift/scan", json={})
    ids = [e["id"] for e in client.get("/drift-events").json()["items"]]
    assert len(ids) == 2

    r = client.post("/drift-events/bulk", json={"ids": ids, "status": "resolved"}).json()
    assert r["updated"] == 2
    assert client.get("/drift-events", params={"status": "resolved"}).json()["total"] == 2
    assert client.post("/drift-events/bulk", json={"ids": ids}).status_code == 422
    assert client.post("/drift-events/bulk", json={"ids": ids, "delete": True}).json()["updated"] == 2
    assert client.get("/drift-events").json()["total"] == 0


def test_system_config_hides_secrets(client, auth_on):
    body = client.get("/system/config", headers={"X-API-Key": "key-123"}).json()
    text = str(body)
    assert "s3cret-pass" not in text and "key-123" not in text and "test-secret" not in text
    assert body["config"]["auth_enabled"] is True


def test_new_ui_pages_render(client):
    client.post("/demo/traffic", params={"requests": 30})
    client.post("/drift/scan", json={})
    for url in [
        "/ui?range=7d",
        "/ui?range=30d",
        "/ui/endpoint?method=GET&path=/api/products/{product_id}",
        "/ui/endpoint?method=POST&path=/api/users&range=7d",
        "/ui/playground",
        "/ui/playground?all=true",
        "/ui/settings",
    ]:
        resp = client.get(url)
        assert resp.status_code == 200, url
    assert client.get("/ui/endpoint?method=GET&path=/missing").status_code == 404


def test_liveness_route_is_public_and_db_free(client, auth_on, monkeypatch):
    from app.database import session

    def boom(*args, **kwargs):
        raise AssertionError("liveness must not touch the database")

    monkeypatch.setattr(session, "SessionLocal", boom)
    monkeypatch.setattr(session, "check_db", boom)
    resp = client.get("/health/live")
    assert resp.status_code == 200 and resp.json()["status"] == "alive"
    assert client.head("/health/live").status_code == 200


def test_keep_alive_ping_and_schedule(monkeypatch):
    from app.services import job_service

    calls = []

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(settings, "KEEP_ALIVE_URL", "https://my-app.onrender.com")
    monkeypatch.setattr(settings, "KEEP_ALIVE_INTERVAL_MINUTES", 10)
    monkeypatch.setattr(job_service.httpx, "get", lambda url, timeout, headers: calls.append(url) or FakeResponse())
    monkeypatch.setattr(job_service.JobState, "last_ping_at", None)
    monkeypatch.setattr(job_service.JobState, "last_ping_result", None)

    now = utcnow()
    monkeypatch.setattr(job_service.JobState, "started_at", now)
    assert job_service.keep_alive_due(now) is False  # freshly started instance is awake anyway
    assert job_service.keep_alive_due(now + timedelta(minutes=10)) is True

    result = job_service.keep_alive_ping()
    assert result["ok"] is True
    assert calls == ["https://my-app.onrender.com/health/live"]
    assert job_service.keep_alive_due(utcnow() + timedelta(minutes=5)) is False
    assert job_service.JobState.snapshot()["last_ping_result"]["status_code"] == 200

    monkeypatch.setattr(settings, "KEEP_ALIVE_URL", "")
    assert settings.keep_alive_enabled is False
    assert job_service.keep_alive_due(now + timedelta(days=1)) is False


def test_keep_alive_url_defaults_to_render_url(monkeypatch):
    from app.config import _keep_alive_url

    for name in ("KEEP_ALIVE_URL", "RENDER_EXTERNAL_URL", "PUBLIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert _keep_alive_url() == ""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://public.example.test")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://svc.onrender.com/")
    assert _keep_alive_url() == "https://svc.onrender.com"  # Render's own URL wins over PUBLIC_BASE_URL
    monkeypatch.setenv("KEEP_ALIVE_URL", "https://custom.example.test")
    assert _keep_alive_url() == "https://custom.example.test"
