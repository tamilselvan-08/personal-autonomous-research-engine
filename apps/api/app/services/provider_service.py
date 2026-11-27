"""AI provider configuration: providers, credentials, models, routing, health and usage.

Every function takes ``owner_id`` and only touches that user's rows; another user's ids
behave exactly like ids that do not exist (404).
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlsplit

from sqlalchemy import Integer, String, cast, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.adapters.litellm_adapter import known_model_info
from app.ai.errors import ERROR_HINTS, ProviderError
from app.ai.recorder import AttemptTarget, circuit_is_open
from app.ai.registry import PROVIDER_SPECS, AdapterFactory, ProviderSpec, get_spec
from app.ai.router import AIRoutingError, ModelRouter, resolve_base_url
from app.ai.types import ChatMessage, CompletionRequest, ProviderCallConfig
from app.core.config import Settings
from app.core.crypto import (
    DecryptionError,
    EncryptionNotConfiguredError,
    encryption_configured,
    get_keyring,
)
from app.core.errors import AppError, ConflictError, FieldValidationError, NotFoundError
from app.models import AIModel, AIProvider, ModelRoute, RoutingPolicy, UsageRecord
from app.models.enums import (
    HealthState,
    ModelCapability,
    ModelRole,
    ProviderType,
    UsageOutcome,
    UsagePurpose,
)
from app.schemas.ai import (
    AttemptOut,
    ConnectionTestIn,
    ConnectionTestOut,
    DiscoveredModelOut,
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
    ProviderHealthOut,
    ProviderOut,
    ProviderTypeOut,
    ProviderTypesOut,
    ProviderUpdate,
    RoleRouteOut,
    RouteEntryOut,
    RoutesOut,
    RouteUpdate,
    RoutingPolicyOut,
    RoutingPolicyUpdate,
    RoutingTestOut,
    UsageGroupBy,
    UsageRecordOut,
    UsageRowOut,
    UsageSummaryOut,
)
from app.schemas.common import Page, PaginationParams, make_page
from app.services import audit_service, secret_service

NAME_TAKEN = "A provider with this name already exists."
MODEL_TAKEN = "This model is already configured for the provider."
CONNECTION_TEST_PROMPT = "Reply with the single word: OK"


class EncryptionUnavailableError(AppError):
    status_code = 503
    code = "ENCRYPTION_NOT_CONFIGURED"


def _require_keyring(settings: Settings):  # type: ignore[no-untyped-def]
    try:
        return get_keyring(settings)
    except EncryptionNotConfiguredError as exc:
        raise EncryptionUnavailableError(str(exc)) from exc


# --- serialisation ----------------------------------------------------------------------


def _route_roles(db: Session, owner_id: uuid.UUID) -> dict[uuid.UUID, list[ModelRole]]:
    out: dict[uuid.UUID, list[ModelRole]] = {}
    for model_id, role in db.execute(
        select(ModelRoute.model_id, ModelRoute.role)
        .where(ModelRoute.owner_id == owner_id)
        .order_by(ModelRoute.role)
    ):
        out.setdefault(model_id, []).append(ModelRole(role))
    return out


def model_capabilities(model: AIModel) -> list[ModelCapability]:
    caps = {ModelCapability(c) for c in model.capabilities or [] if c in ModelCapability}
    if model.supports_json:
        caps.add(ModelCapability.JSON)
    return sorted(caps)


def _set_capabilities(model: AIModel, caps: list[ModelCapability]) -> None:
    model.supports_json = ModelCapability.JSON in caps
    model.capabilities = sorted(c.value for c in caps if c is not ModelCapability.JSON)


def connection_status(provider: AIProvider) -> str:
    if not provider.enabled:
        return "disabled"
    if provider.health_state == HealthState.HEALTHY.value:
        return "connected"
    if provider.health_state == HealthState.UNKNOWN.value or (
        provider.last_tested_at is None and provider.last_success_at is None
    ):
        return "not_tested"
    return "failing"


def _model_out(model: AIModel, roles: dict[uuid.UUID, list[ModelRole]]) -> ModelOut:
    return ModelOut(
        id=model.id,
        provider_id=model.provider_id,
        model_identifier=model.model_identifier,
        display_name=model.display_name,
        context_window=model.context_window,
        input_price_per_mtok=model.input_price_per_mtok,
        output_price_per_mtok=model.output_price_per_mtok,
        supports_json=model.supports_json,
        capabilities=model_capabilities(model),
        enabled=model.enabled,
        health_state=model.health_state,
        last_error_class=model.last_error_class,
        last_error_message=model.last_error_message,
        last_error_at=model.last_error_at,
        last_success_at=model.last_success_at,
        circuit_open=circuit_is_open(model.circuit_opened_at),
        route_roles=roles.get(model.id, []),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _provider_out(
    provider: AIProvider, roles: dict[uuid.UUID, list[ModelRole]] | None = None
) -> ProviderOut:
    spec = get_spec(provider.provider_type)
    secret = provider.secret
    roles = roles or {}
    return ProviderOut(
        id=provider.id,
        provider_type=ProviderType(provider.provider_type),
        provider_label=spec.label,
        display_name=provider.display_name,
        base_url=provider.base_url,
        effective_base_url=resolve_base_url(provider.provider_type, provider.base_url),
        enabled=provider.enabled,
        has_key=secret is not None,
        key_masked=secret_service.mask(secret.last4) if secret else None,
        key_updated_at=(secret.rotated_at or secret.created_at) if secret else None,
        health_state=provider.health_state,
        connection_status=connection_status(provider),
        consecutive_failures=provider.consecutive_failures,
        last_error_class=provider.last_error_class,
        last_error_message=provider.last_error_message,
        last_error_at=provider.last_error_at,
        last_success_at=provider.last_success_at,
        last_tested_at=provider.last_tested_at,
        verification=spec.verification,
        models=[_model_out(m, roles) for m in provider.models],
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


def list_types(settings: Settings) -> ProviderTypesOut:
    return ProviderTypesOut(
        encryption_configured=encryption_configured(settings),
        types=[
            ProviderTypeOut(
                type=s.type,
                label=s.label,
                protocol=s.protocol,
                default_base_url=s.default_base_url,
                requires_base_url=s.requires_base_url,
                api_key_required=s.api_key_required,
                allow_http=s.allow_http,
                key_hint=s.key_hint,
                docs_url=s.docs_url,
                model_examples=list(s.model_examples),
                verification=s.verification,
            )
            for s in PROVIDER_SPECS.values()
        ],
    )


# --- lookups ----------------------------------------------------------------------------


def get_owned(db: Session, owner_id: uuid.UUID, provider_id: uuid.UUID) -> AIProvider:
    provider = db.scalar(
        select(AIProvider).where(AIProvider.id == provider_id, AIProvider.owner_id == owner_id)
    )
    if provider is None:
        raise NotFoundError("AI provider not found.")
    return provider


def get_owned_model(db: Session, owner_id: uuid.UUID, model_id: uuid.UUID) -> AIModel:
    model = db.scalar(select(AIModel).where(AIModel.id == model_id, AIModel.owner_id == owner_id))
    if model is None:
        raise NotFoundError("Model not found.")
    return model


def _name_exists(
    db: Session, owner_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> bool:
    stmt = select(AIProvider.id).where(
        AIProvider.owner_id == owner_id, func.lower(AIProvider.display_name) == name.lower()
    )
    if exclude_id:
        stmt = stmt.where(AIProvider.id != exclude_id)
    return db.scalar(stmt) is not None


def normalize_base_url(spec: ProviderSpec, value: str | None) -> str | None:
    """Validate a base URL for ``spec``. Returns None when it equals the default."""
    if value is None:
        if spec.requires_base_url:
            raise FieldValidationError("base_url", "A base URL is required for this provider.")
        return None
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise FieldValidationError("base_url", "Enter a valid URL.") from exc
    allowed = {"https", "http"} if spec.allow_http else {"https"}
    if parts.scheme not in allowed or not parts.hostname:
        msg = (
            "Enter an http:// or https:// URL."
            if spec.allow_http
            else "Enter an https:// URL for this provider."
        )
        raise FieldValidationError("base_url", msg)
    if parts.username or parts.password:
        raise FieldValidationError(
            "base_url", "Don't put credentials in the URL; use the API key field."
        )
    if parts.query or parts.fragment:
        raise FieldValidationError("base_url", "The base URL must not have a query or fragment.")
    normalized = value.rstrip("/")
    if spec.default_base_url and normalized == spec.default_base_url.rstrip("/"):
        return None
    return normalized


def _audit(db: Session, owner_id: uuid.UUID, action: str, entity_type: str, entity_id, data):  # type: ignore[no-untyped-def]
    audit_service.record(
        db,
        actor_id=owner_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        data=data,
    )


# --- providers --------------------------------------------------------------------------


def list_providers(db: Session, owner_id: uuid.UUID) -> list[ProviderOut]:
    providers = db.scalars(
        select(AIProvider)
        .where(AIProvider.owner_id == owner_id)
        .order_by(AIProvider.created_at, AIProvider.id)
    ).unique()
    roles = _route_roles(db, owner_id)
    return [_provider_out(p, roles) for p in providers]


def get_provider(db: Session, owner_id: uuid.UUID, provider_id: uuid.UUID) -> ProviderOut:
    return _provider_out(get_owned(db, owner_id, provider_id), _route_roles(db, owner_id))


def _new_model(provider: AIProvider, data: ModelCreate) -> AIModel:
    model = AIModel(
        provider_id=provider.id,
        owner_id=provider.owner_id,
        model_identifier=data.model_identifier,
        display_name=data.display_name,
        context_window=data.context_window,
        input_price_per_mtok=data.input_price_per_mtok,
        output_price_per_mtok=data.output_price_per_mtok,
        supports_json=bool(data.supports_json),
        capabilities=[],
        enabled=data.enabled if data.enabled is not None else True,
    )
    if data.capabilities is not None:
        _set_capabilities(model, data.capabilities)
    _prefill_from_litellm(provider, model, data)
    return model


def _prefill_from_litellm(provider: AIProvider, model: AIModel, data: ModelCreate) -> None:
    """Fill fields the user left empty from LiteLLM's model map (FR-LLM-002).

    Hosted providers only: a local/compatible endpoint's model name says nothing reliable
    about its limits or price. Values stay editable.
    """
    spec = get_spec(provider.provider_type)
    if spec.type is ProviderType.OPENAI_COMPATIBLE:
        return
    info = known_model_info(spec.litellm_provider, model.model_identifier)
    if info is None:
        return
    if data.context_window is None:
        model.context_window = info.context_window
    if data.input_price_per_mtok is None:
        model.input_price_per_mtok = info.input_price_per_mtok
    if data.output_price_per_mtok is None:
        model.output_price_per_mtok = info.output_price_per_mtok
    if data.capabilities is None and data.supports_json is None:
        _set_capabilities(model, [ModelCapability(c) for c in info.capabilities])


def create_provider(
    db: Session, settings: Settings, owner_id: uuid.UUID, data: ProviderCreate
) -> ProviderOut:
    spec = PROVIDER_SPECS[data.provider_type]
    base_url = normalize_base_url(spec, data.base_url)
    if spec.api_key_required and data.api_key is None:
        raise FieldValidationError("api_key", "An API key is required for this provider.")
    if _name_exists(db, owner_id, data.display_name):
        raise ConflictError(NAME_TAKEN, code="PROVIDER_NAME_TAKEN")

    secret = None
    if data.api_key is not None:
        keyring = _require_keyring(settings)
        secret = secret_service.store(db, keyring, owner_id, data.api_key.get_secret_value())

    provider = AIProvider(
        owner_id=owner_id,
        provider_type=spec.type.value,
        display_name=data.display_name,
        base_url=base_url,
        secret=secret,
        enabled=data.enabled,
    )
    db.add(provider)
    try:
        db.flush()
        for m in data.models:
            db.add(_new_model(provider, m))
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(NAME_TAKEN, code="PROVIDER_NAME_TAKEN") from exc
    _audit(
        db,
        owner_id,
        "ai_provider.created",
        "ai_provider",
        provider.id,
        {"type": spec.type.value, "name": provider.display_name, "has_key": secret is not None},
    )
    db.commit()
    db.refresh(provider)
    return get_provider(db, owner_id, provider.id)


def update_provider(
    db: Session, owner_id: uuid.UUID, provider_id: uuid.UUID, data: ProviderUpdate
) -> ProviderOut:
    provider = get_owned(db, owner_id, provider_id)
    spec = get_spec(provider.provider_type)
    changes = data.model_dump(exclude_unset=True)
    if "display_name" in changes:
        if changes["display_name"] is None:
            changes.pop("display_name")
        elif _name_exists(db, owner_id, changes["display_name"], exclude_id=provider.id):
            raise ConflictError(NAME_TAKEN, code="PROVIDER_NAME_TAKEN")
    if "base_url" in changes:
        changes["base_url"] = normalize_base_url(spec, changes["base_url"])
    if "enabled" in changes and changes["enabled"] is None:
        changes.pop("enabled")
    if not changes:
        return get_provider(db, owner_id, provider.id)
    if changes.get("base_url", provider.base_url) != provider.base_url:
        # A different endpoint: previous health no longer says anything.
        provider.health_state = HealthState.UNKNOWN.value
        provider.consecutive_failures = 0
    for field, value in changes.items():
        setattr(provider, field, value)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(NAME_TAKEN, code="PROVIDER_NAME_TAKEN") from exc
    _audit(
        db, owner_id, "ai_provider.updated", "ai_provider", provider.id, {"fields": sorted(changes)}
    )
    db.commit()
    db.refresh(provider)
    return get_provider(db, owner_id, provider.id)


def set_provider_enabled(
    db: Session, owner_id: uuid.UUID, provider_id: uuid.UUID, enabled: bool
) -> ProviderOut:
    return update_provider(db, owner_id, provider_id, ProviderUpdate(enabled=enabled))


def _roles_using(db: Session, owner_id: uuid.UUID, model_ids: list[uuid.UUID]) -> list[str]:
    if not model_ids:
        return []
    return sorted(
        set(
            db.scalars(
                select(ModelRoute.role).where(
                    ModelRoute.owner_id == owner_id, ModelRoute.model_id.in_(model_ids)
                )
            )
        )
    )


def _compact_routes(db: Session, owner_id: uuid.UUID) -> None:
    """Renumber positions 0..n-1 per role after entries were removed."""
    routes = list(
        db.scalars(
            select(ModelRoute)
            .where(ModelRoute.owner_id == owner_id)
            .order_by(ModelRoute.role, ModelRoute.position)
        )
    )
    by_role: dict[str, list[ModelRoute]] = {}
    for r in routes:
        by_role.setdefault(r.role, []).append(r)
    for entries in by_role.values():
        if [e.position for e in entries] == list(range(len(entries))):
            continue
        # Two passes avoid transient unique-constraint clashes.
        for e in entries:
            e.position = e.position + 1000
        db.flush()
        for i, e in enumerate(entries):
            e.position = i
        db.flush()


def delete_provider(
    db: Session, owner_id: uuid.UUID, provider_id: uuid.UUID, *, force: bool
) -> None:
    provider = get_owned(db, owner_id, provider_id)
    roles = _roles_using(db, owner_id, [m.id for m in provider.models])
    if roles and not force:
        raise ConflictError(
            "This provider's models are used in routing ("
            + ", ".join(roles)
            + "). Delete with force=true to remove them from routing too.",
            code="PROVIDER_IN_USE",
            details={"roles": roles},
        )
    secret = provider.secret
    _audit(
        db,
        owner_id,
        "ai_provider.deleted",
        "ai_provider",
        provider.id,
        {"name": provider.display_name, "type": provider.provider_type, "removed_from": roles},
    )
    db.delete(provider)
    db.flush()
    if secret is not None:
        db.delete(secret)
    db.flush()
    _compact_routes(db, owner_id)
    db.commit()


def replace_key(
    db: Session, settings: Settings, owner_id: uuid.UUID, provider_id: uuid.UUID, data: KeyReplace
) -> ProviderOut:
    provider = get_owned(db, owner_id, provider_id)
    keyring = _require_keyring(settings)
    old = provider.secret
    provider.secret = secret_service.store(db, keyring, owner_id, data.api_key.get_secret_value())
    provider.health_state = HealthState.UNKNOWN.value
    provider.consecutive_failures = 0
    db.flush()
    if old is not None:
        db.delete(old)
    _audit(
        db,
        owner_id,
        "ai_provider.key_replaced",
        "ai_provider",
        provider.id,
        {"had_key": old is not None},
    )
    db.commit()
    db.refresh(provider)
    return get_provider(db, owner_id, provider.id)


def remove_key(db: Session, owner_id: uuid.UUID, provider_id: uuid.UUID) -> ProviderOut:
    provider = get_owned(db, owner_id, provider_id)
    old = provider.secret
    if old is None:
        return get_provider(db, owner_id, provider.id)
    provider.secret = None
    provider.health_state = HealthState.UNKNOWN.value
    db.flush()
    db.delete(old)
    _audit(db, owner_id, "ai_provider.key_removed", "ai_provider", provider.id, {})
    db.commit()
    db.refresh(provider)
    return get_provider(db, owner_id, provider.id)


# --- models -----------------------------------------------------------------------------


def list_models(db: Session, owner_id: uuid.UUID, provider_id: uuid.UUID) -> list[ModelOut]:
    provider = get_owned(db, owner_id, provider_id)
    roles = _route_roles(db, owner_id)
    return [_model_out(m, roles) for m in provider.models]


def list_all_models(
    db: Session, owner_id: uuid.UUID, provider_id: uuid.UUID | None = None
) -> list[ModelOut]:
    """Every model the user configured, across providers (optionally one provider)."""
    query = (
        select(AIModel)
        .join(AIProvider, AIModel.provider_id == AIProvider.id)
        .where(AIModel.owner_id == owner_id)
        .order_by(func.lower(AIProvider.display_name), AIModel.model_identifier)
    )
    if provider_id is not None:
        get_owned(db, owner_id, provider_id)  # 404 for another user's provider
        query = query.where(AIModel.provider_id == provider_id)
    roles = _route_roles(db, owner_id)
    return [_model_out(m, roles) for m in db.scalars(query).unique()]


def add_model_for_provider(
    db: Session, owner_id: uuid.UUID, data: ModelCreateForProvider
) -> ModelOut:
    fields = data.model_dump(exclude={"provider_id"}, exclude_unset=True)
    return add_model(db, owner_id, data.provider_id, ModelCreate(**fields))


def add_model(
    db: Session, owner_id: uuid.UUID, provider_id: uuid.UUID, data: ModelCreate
) -> ModelOut:
    provider = get_owned(db, owner_id, provider_id)
    if any(m.model_identifier == data.model_identifier for m in provider.models):
        raise ConflictError(MODEL_TAKEN, code="MODEL_ALREADY_CONFIGURED")
    model = _new_model(provider, data)
    db.add(model)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(MODEL_TAKEN, code="MODEL_ALREADY_CONFIGURED") from exc
    _audit(
        db,
        owner_id,
        "ai_model.created",
        "ai_model",
        model.id,
        {"provider_id": str(provider.id), "model": model.model_identifier},
    )
    db.commit()
    db.refresh(model)
    return _model_out(model, _route_roles(db, owner_id))


def update_model(
    db: Session, owner_id: uuid.UUID, model_id: uuid.UUID, data: ModelUpdate
) -> ModelOut:
    model = get_owned_model(db, owner_id, model_id)
    changes = {
        k: v
        for k, v in data.model_dump(exclude_unset=True).items()
        if v is not None
        or k in {"display_name", "context_window", "input_price_per_mtok", "output_price_per_mtok"}
    }
    caps = changes.pop("capabilities", None)
    for field, value in changes.items():
        setattr(model, field, value)
    if caps is not None:
        _set_capabilities(model, [ModelCapability(c) for c in caps])
        changes["capabilities"] = caps
    if changes:
        if "enabled" in changes and changes["enabled"]:
            model.circuit_opened_at = None
        _audit(db, owner_id, "ai_model.updated", "ai_model", model.id, {"fields": sorted(changes)})
        db.commit()
        db.refresh(model)
    return _model_out(model, _route_roles(db, owner_id))


def delete_model(db: Session, owner_id: uuid.UUID, model_id: uuid.UUID, *, force: bool) -> None:
    model = get_owned_model(db, owner_id, model_id)
    roles = _roles_using(db, owner_id, [model.id])
    if roles and not force:
        raise ConflictError(
            f"This model is used in routing ({', '.join(roles)}). Delete with force=true to "
            "remove it from routing too.",
            code="MODEL_IN_USE",
            details={"roles": roles},
        )
    _audit(
        db,
        owner_id,
        "ai_model.deleted",
        "ai_model",
        model.id,
        {"model": model.model_identifier, "removed_from": roles},
    )
    db.delete(model)
    db.flush()
    _compact_routes(db, owner_id)
    db.commit()


# --- routing ----------------------------------------------------------------------------


def _availability(model: AIModel) -> tuple[bool, str | None]:
    provider = model.provider
    spec = get_spec(provider.provider_type)
    if not provider.enabled:
        return False, "Provider is disabled."
    if not model.enabled:
        return False, "Model is disabled."
    if provider.secret_id is None and spec.api_key_required:
        return False, "Provider has no API key."
    if circuit_is_open(model.circuit_opened_at):
        return False, "Temporarily skipped after repeated failures."
    return True, None


def get_routes(db: Session, owner_id: uuid.UUID) -> RoutesOut:
    rows = list(
        db.scalars(
            select(ModelRoute)
            .where(ModelRoute.owner_id == owner_id)
            .order_by(ModelRoute.role, ModelRoute.position)
        )
    )
    by_role: dict[str, list[ModelRoute]] = {}
    for r in rows:
        by_role.setdefault(r.role, []).append(r)
    out = []
    for role in ModelRole:
        entries = []
        for r in by_role.get(role.value, []):
            available, reason = _availability(r.model)
            entries.append(
                RouteEntryOut(
                    position=r.position,
                    model_id=r.model_id,
                    model_identifier=r.model.model_identifier,
                    model_display_name=r.model.display_name,
                    provider_id=r.model.provider_id,
                    provider_name=r.model.provider.display_name,
                    provider_type=ProviderType(r.model.provider.provider_type),
                    available=available,
                    unavailable_reason=reason,
                    health_state=r.model.provider.health_state
                    if r.model.provider.health_state != HealthState.HEALTHY.value
                    else r.model.health_state,
                )
            )
        out.append(
            RoleRouteOut(
                role=role,
                uses_default=role is not ModelRole.DEFAULT and not entries,
                entries=entries,
            )
        )
    return RoutesOut(roles=out)


def _apply_route(
    db: Session, owner_id: uuid.UUID, role: ModelRole, model_ids: list[uuid.UUID]
) -> None:
    """Validate and replace one role's chain. Does not commit."""
    models = []
    for i, model_id in enumerate(model_ids):
        model = db.scalar(
            select(AIModel).where(AIModel.id == model_id, AIModel.owner_id == owner_id)
        )
        if model is None:
            raise FieldValidationError("model_ids", f"Model #{i + 1} was not found.")
        if not model.enabled or not model.provider.enabled:
            raise FieldValidationError(
                "model_ids",
                f"'{model.model_identifier}' ({model.provider.display_name}) is disabled. "
                "Enable it before adding it to routing.",
            )
        models.append(model)
    db.execute(
        delete(ModelRoute).where(ModelRoute.owner_id == owner_id, ModelRoute.role == role.value)
    )
    db.flush()
    for position, model in enumerate(models):
        db.add(ModelRoute(owner_id=owner_id, role=role.value, position=position, model_id=model.id))
    _audit(
        db,
        owner_id,
        "model_route.updated",
        "model_route",
        None,
        {"role": role.value, "models": [m.model_identifier for m in models]},
    )


def set_route(db: Session, owner_id: uuid.UUID, role: ModelRole, data: RouteUpdate) -> RoutesOut:
    _apply_route(db, owner_id, role, data.model_ids)
    db.commit()
    return get_routes(db, owner_id)


def get_routing(db: Session, owner_id: uuid.UUID) -> ModelRoutingOut:
    return ModelRoutingOut(roles=get_routes(db, owner_id).roles, policy=get_policy(db, owner_id))


def set_routing(db: Session, owner_id: uuid.UUID, data: ModelRoutingUpdate) -> ModelRoutingOut:
    """Apply several chains and/or the policy atomically: all of it, or none of it."""
    try:
        for role, model_ids in data.routes.items():
            _apply_route(db, owner_id, role, model_ids)
        if data.policy is not None:
            _apply_policy(db, owner_id, data.policy)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_routing(db, owner_id)


def get_policy(db: Session, owner_id: uuid.UUID) -> RoutingPolicyOut:
    row = db.get(RoutingPolicy, owner_id)
    if row is None:
        return RoutingPolicyOut(
            max_retries=2,
            max_retry_after_seconds=20,
            fallback_on_rate_limit=True,
            fallback_on_quota_exhausted=False,
        )
    return RoutingPolicyOut(
        max_retries=row.max_retries,
        max_retry_after_seconds=row.max_retry_after_seconds,
        fallback_on_rate_limit=row.fallback_on_rate_limit,
        fallback_on_quota_exhausted=row.fallback_on_quota_exhausted,
    )


def _apply_policy(db: Session, owner_id: uuid.UUID, data: RoutingPolicyUpdate) -> None:
    """Merge policy changes. Does not commit."""
    current = get_policy(db, owner_id).model_dump()
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    current.update(changes)
    row = db.get(RoutingPolicy, owner_id)
    if row is None:
        row = RoutingPolicy(owner_id=owner_id, **current)
        db.add(row)
    else:
        for k, v in current.items():
            setattr(row, k, v)
    _audit(db, owner_id, "routing_policy.updated", "routing_policy", None, changes)


def update_policy(db: Session, owner_id: uuid.UUID, data: RoutingPolicyUpdate) -> RoutingPolicyOut:
    _apply_policy(db, owner_id, data)
    db.commit()
    return get_policy(db, owner_id)


# --- connection tests & discovery -------------------------------------------------------


def _call_config_parts(
    db: Session, settings: Settings, provider: AIProvider
) -> tuple[str, str | None]:
    base_url = resolve_base_url(provider.provider_type, provider.base_url)
    api_key = None
    if provider.secret is not None:
        keyring = _require_keyring(settings)
        try:
            api_key = secret_service.reveal(keyring, provider.secret, provider.owner_id)
        except DecryptionError as exc:
            raise AppError(
                "The stored API key could not be decrypted (was SECRETS_MASTER_KEY changed?). "
                "Enter the key again.",
                code="CREDENTIAL_UNREADABLE",
                status_code=409,
            ) from exc
    elif get_spec(provider.provider_type).api_key_required:
        raise AppError("Add an API key before testing.", code="NO_API_KEY", status_code=409)
    return base_url, api_key


def test_connection(
    db: Session,
    settings: Settings,
    router: ModelRouter,
    owner_id: uuid.UUID,
    provider_id: uuid.UUID,
    data: ConnectionTestIn,
) -> ConnectionTestOut:
    provider = get_owned(db, owner_id, provider_id)
    model: AIModel | None = None
    if data.model_id is not None:
        model = next((m for m in provider.models if m.id == data.model_id), None)
        if model is None:
            raise FieldValidationError("model_id", "That model does not belong to this provider.")
        identifier = model.model_identifier
    elif data.model_identifier:
        identifier = data.model_identifier
        model = next((m for m in provider.models if m.model_identifier == identifier), None)
    else:
        model = next((m for m in provider.models if m.enabled), None) or next(
            iter(provider.models), None
        )
        if model is None:
            raise FieldValidationError(
                "model_id", "Add a model to this provider (or name one) before testing."
            )
        identifier = model.model_identifier

    base_url, api_key = _call_config_parts(db, settings, provider)
    target = AttemptTarget(
        owner_id=owner_id,
        provider_id=provider.id,
        provider_type=provider.provider_type,
        provider_name=provider.display_name,
        model_id=model.id if model else None,
        model_identifier=identifier,
        input_price_per_mtok=model.input_price_per_mtok if model else None,
        output_price_per_mtok=model.output_price_per_mtok if model else None,
    )
    request = CompletionRequest(
        messages=[ChatMessage("user", CONNECTION_TEST_PROMPT)], max_output_tokens=5
    )
    response, error, latency = router.call_single(owner_id, target, base_url, api_key, request)
    api_key = None  # drop the plaintext reference as soon as the call is done
    db.expire_all()
    provider = get_owned(db, owner_id, provider_id)
    if error is None:
        return ConnectionTestOut(
            ok=True,
            provider_id=provider.id,
            model_identifier=identifier,
            latency_ms=latency,
            message=f"Connected. {identifier} answered in {latency} ms.",
            health_state=provider.health_state,
            tested_at=provider.last_tested_at or datetime.now(UTC),
        )
    return ConnectionTestOut(
        ok=False,
        provider_id=provider.id,
        model_identifier=identifier,
        latency_ms=latency,
        error_class=error.error_class.value,
        error_hint=ERROR_HINTS.get(error.error_class),
        message=error.message,
        http_status=error.http_status,
        health_state=provider.health_state,
        tested_at=provider.last_tested_at or datetime.now(UTC),
    )


def discover_models(
    db: Session,
    settings: Settings,
    adapter_factory: AdapterFactory,
    owner_id: uuid.UUID,
    provider_id: uuid.UUID,
) -> DiscoveredModelsOut:
    provider = get_owned(db, owner_id, provider_id)
    base_url, api_key = _call_config_parts(db, settings, provider)
    spec = get_spec(provider.provider_type)
    cfg = ProviderCallConfig(
        provider_type=provider.provider_type,
        base_url=base_url,
        model="",
        timeout_seconds=settings.ai_connection_test_timeout_seconds,
        api_key=api_key,
    )
    configured = {m.model_identifier for m in provider.models}
    try:
        found = adapter_factory(spec).list_models(cfg)
    except ProviderError as error:
        return DiscoveredModelsOut(
            ok=False,
            models=[],
            error_class=error.error_class.value,
            message=f"{ERROR_HINTS.get(error.error_class, '')} ({error.message})".strip(),
        )
    return DiscoveredModelsOut(
        ok=True,
        models=[
            DiscoveredModelOut(
                id=m.id,
                display_name=m.display_name,
                context_window=m.context_window,
                configured=m.id in configured,
            )
            for m in found[:500]
        ],
    )


def test_routing(router: ModelRouter, owner_id: uuid.UUID, role: ModelRole) -> RoutingTestOut:
    request = CompletionRequest(
        messages=[ChatMessage("user", CONNECTION_TEST_PROMPT)], max_output_tokens=5
    )
    try:
        result = router.complete(owner_id, request, role=role, purpose=UsagePurpose.ROUTING_TEST)
    except AIRoutingError as exc:
        return RoutingTestOut(
            ok=False,
            role=role,
            error_code=exc.code,
            error_class=exc.error_class.value if exc.error_class else None,
            message=exc.message,
            attempts=[AttemptOut(**vars(a)) for a in exc.attempts],
        )
    return RoutingTestOut(
        ok=True,
        role=role,
        provider_name=result.provider_name,
        model_identifier=result.model_identifier,
        latency_ms=result.latency_ms,
        used_fallback=result.used_fallback,
        message=f"Answered by {result.provider_name} / {result.model_identifier}.",
        attempts=[AttemptOut(**vars(a)) for a in result.attempts],
    )


# --- health & usage ---------------------------------------------------------------------


def health_summary(db: Session, owner_id: uuid.UUID, window_hours: int = 24) -> HealthSummaryOut:
    since = datetime.now(UTC) - timedelta(hours=window_hours)
    success = cast(UsageRecord.outcome == UsageOutcome.SUCCESS.value, Integer)
    stats = {
        row.provider_id: row
        for row in db.execute(
            select(
                UsageRecord.provider_id,
                func.count().label("calls"),
                func.coalesce(func.sum(success), 0).label("successes"),
                func.percentile_cont(0.5).within_group(UsageRecord.latency_ms).label("p50"),
                func.percentile_cont(0.95).within_group(UsageRecord.latency_ms).label("p95"),
            )
            .where(
                UsageRecord.owner_id == owner_id,
                UsageRecord.created_at >= since,
                UsageRecord.provider_id.is_not(None),
            )
            .group_by(UsageRecord.provider_id)
        )
    }
    providers = db.scalars(
        select(AIProvider).where(AIProvider.owner_id == owner_id).order_by(AIProvider.created_at)
    ).unique()
    out = []
    for p in providers:
        s = stats.get(p.id)
        calls = int(s.calls) if s else 0
        successes = int(s.successes) if s else 0
        out.append(
            ProviderHealthOut(
                provider_id=p.id,
                display_name=p.display_name,
                provider_type=ProviderType(p.provider_type),
                enabled=p.enabled,
                health_state=p.health_state,
                last_error_class=p.last_error_class,
                last_error_message=p.last_error_message,
                last_error_at=p.last_error_at,
                last_success_at=p.last_success_at,
                last_tested_at=p.last_tested_at,
                window_hours=window_hours,
                calls=calls,
                successes=successes,
                failures=calls - successes,
                success_rate=round(successes / calls, 4) if calls else None,
                p50_latency_ms=round(float(s.p50), 1) if s and s.p50 is not None else None,
                p95_latency_ms=round(float(s.p95), 1) if s and s.p95 is not None else None,
            )
        )
    return HealthSummaryOut(window_hours=window_hours, providers=out)


def usage_summary(
    db: Session,
    owner_id: uuid.UUID,
    group_by: UsageGroupBy,
    date_from: datetime | None,
    date_to: datetime | None,
) -> UsageSummaryOut:
    date_to = date_to or datetime.now(UTC)
    date_from = date_from or date_to - timedelta(days=7)
    if date_from > date_to:
        raise FieldValidationError("date_from", "date_from must be before date_to.")
    if group_by == "provider":
        key = func.coalesce(cast(UsageRecord.provider_id, String), "deleted")
        label = func.max(UsageRecord.provider_name)
    elif group_by == "model":
        key = func.concat(UsageRecord.provider_name, " / ", UsageRecord.model_identifier)
        label = func.max(
            func.concat(UsageRecord.provider_name, " / ", UsageRecord.model_identifier)
        )
    elif group_by == "day":
        key = func.to_char(func.date_trunc("day", UsageRecord.created_at), "YYYY-MM-DD")
        label = func.max(func.to_char(func.date_trunc("day", UsageRecord.created_at), "YYYY-MM-DD"))
    elif group_by == "purpose":
        key = UsageRecord.purpose
        label = func.max(UsageRecord.purpose)
    else:
        key = UsageRecord.outcome
        label = func.max(UsageRecord.outcome)

    success = cast(UsageRecord.outcome == UsageOutcome.SUCCESS.value, Integer)
    metrics = (
        func.count().label("calls"),
        func.coalesce(func.sum(success), 0).label("successes"),
        func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
        func.sum(UsageRecord.est_cost_usd).label("cost"),
        func.avg(UsageRecord.latency_ms).label("avg_latency"),
    )
    where = (
        UsageRecord.owner_id == owner_id,
        UsageRecord.created_at >= date_from,
        UsageRecord.created_at <= date_to,
    )
    rows = db.execute(
        select(key.label("key"), label.label("label"), *metrics)
        .where(*where)
        .group_by(key)
        .order_by(key)
    ).all()
    total = db.execute(select(*metrics).where(*where)).one()

    def _row(k: str, lbl: str, r) -> UsageRowOut:  # type: ignore[no-untyped-def]
        calls = int(r.calls)
        return UsageRowOut(
            key=k,
            label=lbl,
            calls=calls,
            successes=int(r.successes),
            failures=calls - int(r.successes),
            input_tokens=int(r.input_tokens),
            output_tokens=int(r.output_tokens),
            est_cost_usd=Decimal(r.cost) if r.cost is not None else None,
            avg_latency_ms=round(float(r.avg_latency), 1) if r.avg_latency is not None else None,
        )

    return UsageSummaryOut(
        date_from=date_from,
        date_to=date_to,
        group_by=group_by,
        rows=[_row(str(r.key), str(r.label), r) for r in rows],
        totals=_row("total", "Total", total),
    )


def list_usage_records(
    db: Session, owner_id: uuid.UUID, params: PaginationParams, provider_id: uuid.UUID | None
) -> Page[UsageRecordOut]:
    base = select(UsageRecord).where(UsageRecord.owner_id == owner_id)
    if provider_id is not None:
        base = base.where(UsageRecord.provider_id == provider_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(UsageRecord.created_at.desc(), UsageRecord.attempt.desc())
        .offset(params.offset)
        .limit(params.page_size)
    )
    return make_page([UsageRecordOut.model_validate(r) for r in rows], total, params)
