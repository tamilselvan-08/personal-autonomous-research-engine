"""Test fixtures. Tests run against a real PostgreSQL database (never SQLite).

Set TEST_DATABASE_URL to point at a disposable database. It is created if missing,
migrated with Alembic once per session, and truncated between tests.
"""

import os
import secrets
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://pare:pare@localhost:5432/pare_test"
)

# Configure the app before it is imported anywhere.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ALLOW_REGISTRATION"] = "true"
# A fixed test-only key-encryption key (32 zero-padded bytes, never used outside tests).
os.environ["SECRETS_MASTER_KEY"] = "dGVzdC1vbmx5LWtleS1lbmNyeXB0aW9uLWtleS0zMmI"
os.environ["SECRETS_MASTER_KEY_ID"] = "test1"
os.environ.pop("SECRETS_PREVIOUS_KEYS", None)

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from alembic import command  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]
TABLES = [
    "usage_records",
    "model_routes",
    "ai_routing_policies",
    "ai_models",
    "ai_providers",
    "secrets",
    "audit_events",
    "research_tasks",
    "projects",
    "users",
]


def _ensure_database(url: str) -> None:
    parsed = make_url(url)
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": parsed.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    admin.dispose()


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    os.environ["DATABASE_URL"] = url
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    _ensure_database(TEST_DATABASE_URL)
    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")
    yield


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    yield
    from app.core.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    from app.api.v1.routes import auth as auth_routes

    if auth_routes._login_limiter is not None:
        auth_routes._login_limiter.reset()
    from app.api.v1.routes import ai_providers as ai_routes

    if ai_routes._test_limiter is not None:
        ai_routes._test_limiter.reset()


@pytest.fixture
def app():  # type: ignore[no-untyped-def]
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    return create_app()


@pytest.fixture
def make_client(app) -> Callable[..., TestClient]:  # type: ignore[no-untyped-def]
    def _make(csrf: bool = True) -> TestClient:
        headers = {"X-PARE-CSRF": "1"} if csrf else {}
        return TestClient(app, headers=headers)

    return _make


@pytest.fixture
def client(make_client) -> TestClient:  # type: ignore[no-untyped-def]
    return make_client()


def register(
    client: TestClient,
    email: str = "priya@example.com",
    password: str = "correct-horse-42",
    display_name: str = "Priya",
) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def auth_client(make_client) -> TestClient:  # type: ignore[no-untyped-def]
    c = make_client()
    register(c)
    return c


@pytest.fixture
def other_client(make_client) -> TestClient:  # type: ignore[no-untyped-def]
    c = make_client()
    register(c, email="dev@example.com", display_name="Dev")
    return c


@pytest.fixture
def db_session():  # type: ignore[no-untyped-def]
    from app.core.db import get_session_factory

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
