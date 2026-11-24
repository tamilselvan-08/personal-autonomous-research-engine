import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from tests.conftest import TEST_DATABASE_URL, _ensure_database, alembic_config


def test_health_is_dependency_free(client) -> None:
    for path in ("/health", "/api/v1/health"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.headers["x-request-id"]


def test_request_id_is_echoed(client) -> None:
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    r = client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["x-request-id"] != "bad id with spaces"


def test_readiness_checks_database(client) -> None:
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["database"]["status"] == "ok"


def test_readiness_reports_database_down(client, app) -> None:
    from app.core.db import get_db

    class BrokenSession:
        def execute(self, *_a, **_k):
            raise ConnectionError("db down")

    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        r = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 503
    assert r.json()["checks"]["database"]["status"] == "error"


def test_settings_requires_auth(client) -> None:
    assert client.get("/api/v1/settings").status_code == 401


def test_settings_contents(auth_client) -> None:
    body = auth_client.get("/api/v1/settings").json()
    assert body["app_name"] == "PARE"
    assert body["database"]["status"] == "ok"
    assert body["database"]["version"].startswith("PostgreSQL")
    assert body["database"]["migration_revision"] == "0001"
    assert all(v is False for v in body["features"].values())
    serialized = str(body).lower()
    assert "secret" not in serialized and "password" not in serialized


def test_error_envelope_for_unknown_route(client) -> None:
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    assert set(r.json()["error"]) == {"code", "message", "details", "request_id"}


def test_unhandled_errors_are_generic(app) -> None:
    from fastapi.testclient import TestClient

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "internal detail" not in r.text


def test_openapi_documents_endpoints(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for expected in (
        "/api/v1/health",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/projects",
        "/api/v1/projects/{project_id}",
        "/api/v1/tasks",
        "/api/v1/tasks/{task_id}",
        "/api/v1/tasks/{task_id}/status",
        "/api/v1/settings",
    ):
        assert expected in paths


def test_migrations_round_trip_on_fresh_database() -> None:
    name = f"pare_migr_{uuid.uuid4().hex[:8]}"
    url = make_url(TEST_DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    _ensure_database(url)
    cfg = alembic_config(url)
    try:
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        tables = set(inspect(engine).get_table_names())
        assert {"users", "projects", "research_tasks", "audit_events"} <= tables
        engine.dispose()
        command.downgrade(cfg, "base")
        engine = create_engine(url)
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        engine.dispose()
    finally:
        alembic_config(TEST_DATABASE_URL)  # restore DATABASE_URL for the app
        admin = create_engine(
            make_url(TEST_DATABASE_URL).set(database="postgres"), isolation_level="AUTOCOMMIT"
        )
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
