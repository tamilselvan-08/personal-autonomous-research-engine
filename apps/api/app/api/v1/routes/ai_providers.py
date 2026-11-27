"""AI provider management endpoints. Handlers stay thin: validation via schemas, logic in
``provider_service``, provider calls behind the router/adapters."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.ai.registry import AdapterFactory, default_adapter_factory
from app.ai.router import ModelRouter
from app.api.deps import AppSettings, CurrentUser, DbSession, Pagination
from app.core.config import Settings
from app.core.db import get_session_factory
from app.core.errors import RateLimitedError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.models.enums import ModelRole
from app.schemas.ai import (
    ConnectionTestIn,
    ConnectionTestOut,
    DiscoveredModelsOut,
    HealthSummaryOut,
    KeyReplace,
    ModelCreate,
    ModelCreateForProvider,
    ModelOut,
    ModelRoutingOut,
    ModelRoutingUpdate,
    ModelUpdate,
    ProviderCreate,
    ProviderOut,
    ProviderTypesOut,
    ProviderUpdate,
    RoutesOut,
    RouteUpdate,
    RoutingPolicyOut,
    RoutingPolicyUpdate,
    RoutingTestOut,
    UsageGroupBy,
    UsageRecordOut,
    UsageSummaryOut,
)
from app.schemas.common import ErrorResponse, Page
from app.services import provider_service

router = APIRouter(
    tags=["ai-providers"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)


def get_adapter_factory() -> AdapterFactory:
    """Dependency so tests can swap in adapters backed by a mock HTTP transport."""
    return default_adapter_factory()


AdapterFactoryDep = Annotated[AdapterFactory, Depends(get_adapter_factory)]


def get_model_router(settings: AppSettings, adapters: AdapterFactoryDep) -> ModelRouter:
    return ModelRouter(get_session_factory(), settings, adapters)


RouterDep = Annotated[ModelRouter, Depends(get_model_router)]

_test_limiter: SlidingWindowRateLimiter | None = None


def _check_test_rate(settings: Settings, user_id: uuid.UUID) -> None:
    global _test_limiter
    limit = settings.ai_connection_test_rate_limit_per_minute
    if _test_limiter is None or _test_limiter.limit != limit:
        _test_limiter = SlidingWindowRateLimiter(limit, 60)
    if not _test_limiter.hit(str(user_id)):
        raise RateLimitedError(
            f"Too many provider tests. You can run {limit} per minute; try again shortly."
        )


# --- provider types ---------------------------------------------------------------------


@router.get(
    "/providers/types", response_model=ProviderTypesOut, summary="List supported provider types"
)
def list_provider_types(_: CurrentUser, settings: AppSettings) -> ProviderTypesOut:
    return provider_service.list_types(settings)


@router.get("/providers/health", response_model=HealthSummaryOut, summary="Provider health summary")
def providers_health(
    user: CurrentUser,
    db: DbSession,
    window_hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
) -> HealthSummaryOut:
    return provider_service.health_summary(db, user.id, window_hours)


# --- providers --------------------------------------------------------------------------


@router.get("/providers", response_model=list[ProviderOut], summary="List AI providers")
def list_providers(user: CurrentUser, db: DbSession) -> list[ProviderOut]:
    return provider_service.list_providers(db, user.id)


@router.post(
    "/providers",
    response_model=ProviderOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Add an AI provider (the API key is write-only)",
)
def create_provider(
    data: ProviderCreate, user: CurrentUser, db: DbSession, settings: AppSettings
) -> ProviderOut:
    return provider_service.create_provider(db, settings, user.id, data)


@router.get("/providers/{provider_id}", response_model=ProviderOut, summary="Get a provider")
def get_provider(provider_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProviderOut:
    return provider_service.get_provider(db, user.id, provider_id)


@router.put(
    "/providers/{provider_id}",
    response_model=ProviderOut,
    responses={409: {"model": ErrorResponse}},
    summary="Update a provider (same partial-update body as PATCH)",
)
@router.patch(
    "/providers/{provider_id}",
    response_model=ProviderOut,
    responses={409: {"model": ErrorResponse}},
    summary="Rename, change base URL, or enable/disable a provider",
)
def update_provider(
    provider_id: uuid.UUID, data: ProviderUpdate, user: CurrentUser, db: DbSession
) -> ProviderOut:
    return provider_service.update_provider(db, user.id, provider_id, data)


@router.post(
    "/providers/{provider_id}/enable", response_model=ProviderOut, summary="Enable a provider"
)
def enable_provider(provider_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProviderOut:
    return provider_service.set_provider_enabled(db, user.id, provider_id, True)


@router.post(
    "/providers/{provider_id}/disable",
    response_model=ProviderOut,
    summary="Disable a provider (its models are skipped by routing)",
)
def disable_provider(provider_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProviderOut:
    return provider_service.set_provider_enabled(db, user.id, provider_id, False)


@router.delete(
    "/providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorResponse}},
    summary="Delete a provider, its models and its stored key",
)
def delete_provider(
    provider_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    force: Annotated[bool, Query(description="Also remove its models from routing")] = False,
) -> Response:
    provider_service.delete_provider(db, user.id, provider_id, force=force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/providers/{provider_id}/key",
    response_model=ProviderOut,
    responses={503: {"model": ErrorResponse}},
    summary="Replace the provider's API key",
)
def replace_key(
    provider_id: uuid.UUID,
    data: KeyReplace,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> ProviderOut:
    return provider_service.replace_key(db, settings, user.id, provider_id, data)


@router.delete(
    "/providers/{provider_id}/key",
    response_model=ProviderOut,
    summary="Delete the provider's stored API key",
)
def remove_key(provider_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProviderOut:
    return provider_service.remove_key(db, user.id, provider_id)


@router.post(
    "/providers/{provider_id}/test",
    response_model=ConnectionTestOut,
    responses={409: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    summary="Test the connection with a minimal completion (5 output tokens)",
)
def test_connection(
    provider_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    model_router: RouterDep,
    data: ConnectionTestIn | None = None,
) -> ConnectionTestOut:
    provider_service.get_owned(db, user.id, provider_id)  # 404 before spending the rate limit
    _check_test_rate(settings, user.id)
    return provider_service.test_connection(
        db, settings, model_router, user.id, provider_id, data or ConnectionTestIn()
    )


@router.get(
    "/providers/{provider_id}/available-models",
    response_model=DiscoveredModelsOut,
    responses={429: {"model": ErrorResponse}},
    summary="Ask the provider which models this key can use",
)
def available_models(
    provider_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    adapters: AdapterFactoryDep,
) -> DiscoveredModelsOut:
    provider_service.get_owned(db, user.id, provider_id)
    _check_test_rate(settings, user.id)
    return provider_service.discover_models(db, settings, adapters, user.id, provider_id)


# --- models -----------------------------------------------------------------------------


@router.get(
    "/providers/{provider_id}/models",
    response_model=list[ModelOut],
    summary="List a provider's configured models",
)
def list_models(provider_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[ModelOut]:
    return provider_service.list_models(db, user.id, provider_id)


@router.post(
    "/providers/{provider_id}/models",
    response_model=ModelOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
    summary="Add a model to a provider",
)
def add_model(
    provider_id: uuid.UUID, data: ModelCreate, user: CurrentUser, db: DbSession
) -> ModelOut:
    return provider_service.add_model(db, user.id, provider_id, data)


@router.get("/models", response_model=list[ModelOut], summary="List all configured models")
def list_all_models(
    user: CurrentUser, db: DbSession, provider_id: uuid.UUID | None = None
) -> list[ModelOut]:
    return provider_service.list_all_models(db, user.id, provider_id)


@router.post(
    "/models",
    response_model=ModelOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
    summary="Add a model (provider_id in the body)",
)
def create_model(data: ModelCreateForProvider, user: CurrentUser, db: DbSession) -> ModelOut:
    return provider_service.add_model_for_provider(db, user.id, data)


@router.put(
    "/models/{model_id}",
    response_model=ModelOut,
    summary="Update a model (same partial-update body as PATCH)",
)
@router.patch("/models/{model_id}", response_model=ModelOut, summary="Update a model")
def update_model(
    model_id: uuid.UUID, data: ModelUpdate, user: CurrentUser, db: DbSession
) -> ModelOut:
    return provider_service.update_model(db, user.id, model_id, data)


@router.delete(
    "/models/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorResponse}},
    summary="Delete a model",
)
def delete_model(
    model_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    force: Annotated[bool, Query(description="Also remove it from routing")] = False,
) -> Response:
    provider_service.delete_model(db, user.id, model_id, force=force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- routing ----------------------------------------------------------------------------


@router.get(
    "/model-routes",
    response_model=RoutesOut,
    summary="Primary and fallback chains for every role",
)
def get_routes(user: CurrentUser, db: DbSession) -> RoutesOut:
    return provider_service.get_routes(db, user.id)


@router.put(
    "/model-routes/{role}",
    response_model=RoutesOut,
    summary="Set a role's chain: first model is primary, the rest are fallbacks in order",
)
def set_route(role: ModelRole, data: RouteUpdate, user: CurrentUser, db: DbSession) -> RoutesOut:
    return provider_service.set_route(db, user.id, role, data)


@router.post(
    "/model-routes/{role}/test",
    response_model=RoutingTestOut,
    responses={429: {"model": ErrorResponse}},
    summary="Send a tiny prompt through the chain and report every attempt",
)
def test_route(
    role: ModelRole, user: CurrentUser, settings: AppSettings, model_router: RouterDep
) -> RoutingTestOut:
    _check_test_rate(settings, user.id)
    return provider_service.test_routing(model_router, user.id, role)


@router.get(
    "/model-routing",
    response_model=ModelRoutingOut,
    summary="All routing configuration: chains per role and the retry/fallback policy",
)
def get_model_routing(user: CurrentUser, db: DbSession) -> ModelRoutingOut:
    return provider_service.get_routing(db, user.id)


@router.put(
    "/model-routing",
    response_model=ModelRoutingOut,
    summary="Set several roles' chains and/or the policy in one transaction",
)
def set_model_routing(
    data: ModelRoutingUpdate, user: CurrentUser, db: DbSession
) -> ModelRoutingOut:
    return provider_service.set_routing(db, user.id, data)


@router.get("/routing-policy", response_model=RoutingPolicyOut, summary="Retry/fallback policy")
def get_policy(user: CurrentUser, db: DbSession) -> RoutingPolicyOut:
    return provider_service.get_policy(db, user.id)


@router.put(
    "/routing-policy", response_model=RoutingPolicyOut, summary="Update retry/fallback policy"
)
def update_policy(data: RoutingPolicyUpdate, user: CurrentUser, db: DbSession) -> RoutingPolicyOut:
    return provider_service.update_policy(db, user.id, data)


# --- usage ------------------------------------------------------------------------------


@router.get("/usage", response_model=UsageSummaryOut, summary="Aggregated AI usage")
def usage_summary(
    user: CurrentUser,
    db: DbSession,
    group_by: UsageGroupBy = "provider",
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> UsageSummaryOut:
    return provider_service.usage_summary(db, user.id, group_by, date_from, date_to)


@router.get(
    "/usage/records", response_model=Page[UsageRecordOut], summary="Individual AI call records"
)
def usage_records(
    user: CurrentUser,
    db: DbSession,
    pagination: Pagination,
    provider_id: uuid.UUID | None = None,
) -> Page[UsageRecordOut]:
    return provider_service.list_usage_records(db, user.id, pagination, provider_id)
