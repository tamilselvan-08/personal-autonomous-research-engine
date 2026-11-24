from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class HealthOut(BaseModel):
    status: Literal["ok"]
    version: str
    time: datetime


class CheckResult(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float | None = None
    detail: str | None = None


class ReadinessOut(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, CheckResult]


class DatabaseInfo(BaseModel):
    status: Literal["ok", "error"]
    version: str | None
    latency_ms: float | None
    migration_revision: str | None


class FeatureFlags(BaseModel):
    ai_providers: bool
    research_planning: bool
    research_execution: bool
    browser_manager: bool
    scheduling: bool


class SettingsOut(BaseModel):
    app_name: str
    version: str
    environment: str
    registration_enabled: bool
    api_base_url: str
    server_time: datetime
    default_timezone: str
    python_version: str
    database: DatabaseInfo
    features: FeatureFlags
