from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.core.config import APP_VERSION
from app.schemas.common import ErrorResponse
from app.schemas.system import HealthOut, ReadinessOut, SettingsOut
from app.services import system_service

health_router = APIRouter(tags=["health"])
settings_router = APIRouter(tags=["settings"], responses={401: {"model": ErrorResponse}})


@health_router.get("/health", response_model=HealthOut, summary="Liveness (no dependencies)")
def health() -> HealthOut:
    return HealthOut(status="ok", version=APP_VERSION, time=datetime.now(UTC))


@health_router.get(
    "/health/ready",
    response_model=ReadinessOut,
    responses={503: {"model": ReadinessOut}},
    summary="Readiness (checks the database)",
)
def ready(db: DbSession) -> ReadinessOut | JSONResponse:
    result = system_service.readiness(db)
    if result.status != "ok":
        return JSONResponse(status_code=503, content=result.model_dump(mode="json"))
    return result


@settings_router.get(
    "/settings", response_model=SettingsOut, summary="Application settings and system information"
)
def get_settings_info(_: CurrentUser, db: DbSession, settings: AppSettings) -> SettingsOut:
    return system_service.app_settings(db, settings)
