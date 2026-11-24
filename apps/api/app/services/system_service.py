import logging
import platform
import time
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import APP_VERSION, Settings
from app.schemas.system import (
    CheckResult,
    DatabaseInfo,
    FeatureFlags,
    ReadinessOut,
    SettingsOut,
)

logger = logging.getLogger(__name__)

# Which PRD features this release implements. The UI uses these flags to show
# "Coming soon" instead of controls that do nothing.
FEATURES = FeatureFlags(
    ai_providers=True,
    research_planning=False,
    research_execution=False,
    browser_manager=False,
    scheduling=False,
)


def check_database(db: Session) -> CheckResult:
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # report, don't raise: readiness must answer
        logger.warning("Database health check failed: %s", exc.__class__.__name__)
        return CheckResult(status="error", detail="Database is unreachable.")
    return CheckResult(status="ok", latency_ms=round((time.perf_counter() - started) * 1000, 2))


def readiness(db: Session) -> ReadinessOut:
    database = check_database(db)
    return ReadinessOut(
        status="ok" if database.status == "ok" else "degraded", checks={"database": database}
    )


def _database_info(db: Session) -> DatabaseInfo:
    started = time.perf_counter()
    try:
        version = db.scalar(text("SHOW server_version"))
        revision = db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception as exc:
        db.rollback()
        logger.warning("Database info query failed: %s", exc.__class__.__name__)
        return DatabaseInfo(status="error", version=None, latency_ms=None, migration_revision=None)
    return DatabaseInfo(
        status="ok",
        version=f"PostgreSQL {version}" if version else None,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        migration_revision=revision,
    )


def app_settings(db: Session, settings: Settings) -> SettingsOut:
    return SettingsOut(
        app_name=settings.app_name,
        version=APP_VERSION,
        environment=settings.environment,
        registration_enabled=settings.allow_registration,
        api_base_url=settings.public_api_base_url,
        server_time=datetime.now(UTC),
        default_timezone=settings.default_timezone,
        python_version=platform.python_version(),
        database=_database_info(db),
        features=FEATURES,
    )
