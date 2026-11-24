"""Migrations: upgrade from empty, downgrade, re-upgrade, and no drift from the models."""

import uuid
from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from app.models import Base
from tests.conftest import TEST_DATABASE_URL, _ensure_database, alembic_config

AI_TABLES = {
    "secrets",
    "ai_providers",
    "ai_models",
    "model_routes",
    "ai_routing_policies",
    "usage_records",
}


@pytest.fixture
def scratch_url() -> Iterator[str]:
    name = f"pare_mig_{uuid.uuid4().hex[:8]}"
    url = make_url(TEST_DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    _ensure_database(url)
    yield url
    admin = create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()
    alembic_config(TEST_DATABASE_URL)  # restore DATABASE_URL for the rest of the suite


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade(scratch_url: str) -> None:
    cfg = alembic_config(scratch_url)
    command.upgrade(cfg, "head")
    assert _tables(scratch_url) >= AI_TABLES

    command.downgrade(cfg, "0001")
    remaining = _tables(scratch_url)
    assert not (AI_TABLES & remaining)
    assert {"users", "projects", "research_tasks", "audit_events"} <= remaining

    command.upgrade(cfg, "head")
    assert _tables(scratch_url) >= AI_TABLES


def test_models_match_migrations(scratch_url: str) -> None:
    command.upgrade(alembic_config(scratch_url), "head")
    engine = create_engine(scratch_url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            assert compare_metadata(ctx, Base.metadata) == []
    finally:
        engine.dispose()


def test_constraints_reject_bad_data(scratch_url: str) -> None:
    command.upgrade(alembic_config(scratch_url), "head")
    engine = create_engine(scratch_url)
    try:
        with engine.begin() as conn:
            uid = conn.scalar(
                text(
                    "INSERT INTO users (id, email, display_name, password_hash) "
                    "VALUES (gen_random_uuid(), 'a@b.c', 'A', 'x') RETURNING id"
                )
            )
        for bad in (
            "INSERT INTO ai_providers (id, owner_id, provider_type, display_name) "
            "VALUES (gen_random_uuid(), :u, 'not-a-provider', 'x')",
            "INSERT INTO ai_providers (id, owner_id, provider_type, display_name, health_state) "
            "VALUES (gen_random_uuid(), :u, 'openai', 'x', 'sparkling')",
        ):
            with pytest.raises(Exception, match="check constraint"), engine.begin() as conn:
                conn.execute(text(bad), {"u": uid})
    finally:
        engine.dispose()
