"""Request/response models for AI provider management.

No response model has a field that can carry key material: keys are accepted as
``SecretStr`` (so they never appear in reprs or validation errors) and only ``key_masked``
(e.g. "••••abcd") is ever returned.
"""

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from app.models.enums import ModelRole, ProviderType
from app.schemas.common import strip_or_none

MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,199}$")
MAX_MODELS_PER_REQUEST = 20
MAX_CHAIN_LENGTH = 10


def _validate_model_identifier(value: str) -> str:
    value = value.strip()
    if not MODEL_ID_RE.match(value) or ".." in value:
        raise ValueError(
            "Use the provider's model ID exactly, e.g. 'gpt-4o-mini' (letters, digits and "
            ". _ : / @ + - only)."
        )
    return value


def _validate_display_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Name is required.")
    return value


def _validate_api_key(value: SecretStr | None) -> SecretStr | None:
    if value is None:
        return None
    raw = value.get_secret_value().strip()
    if not raw:
        return None
    if any(ch.isspace() for ch in raw):
        raise ValueError("The API key must not contain spaces or line breaks.")
    if len(raw) > 500:
        raise ValueError("The API key is too long.")
    return SecretStr(raw)


# --- provider types -------------------------------------------------------------------


class ProviderTypeOut(BaseModel):
    type: ProviderType
    label: str
    protocol: str
    default_base_url: str | None
    requires_base_url: bool
    api_key_required: bool
    allow_http: bool
    key_hint: str
    docs_url: str | None
    model_examples: list[str]
    verification: Literal["mocked", "live"]


class ProviderTypesOut(BaseModel):
    encryption_configured: bool
    types: list[ProviderTypeOut]


# --- models -----------------------------------------------------------------------------


class ModelFields(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    context_window: int | None = Field(default=None, gt=0, le=100_000_000)
    input_price_per_mtok: Decimal | None = Field(default=None, ge=0, le=100_000, decimal_places=6)
    output_price_per_mtok: Decimal | None = Field(default=None, ge=0, le=100_000, decimal_places=6)
    supports_json: bool | None = None
    enabled: bool | None = None

    @field_validator("display_name")
    @classmethod
    def _dn(cls, value: str | None) -> str | None:
        return strip_or_none(value)


class ModelCreate(ModelFields):
    model_identifier: str = Field(min_length=1, max_length=200)

    @field_validator("model_identifier")
    @classmethod
    def _mid(cls, value: str) -> str:
        return _validate_model_identifier(value)


class ModelUpdate(ModelFields):
    pass


class ModelOut(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    model_identifier: str
    display_name: str | None
    context_window: int | None
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    supports_json: bool
    enabled: bool
    health_state: str
    last_error_class: str | None
    last_error_message: str | None
    last_error_at: datetime | None
    last_success_at: datetime | None
    circuit_open: bool
    route_roles: list[ModelRole]
    created_at: datetime
    updated_at: datetime


# --- providers --------------------------------------------------------------------------


class ProviderCreate(BaseModel):
    provider_type: ProviderType
    display_name: str = Field(min_length=1, max_length=100)
    api_key: SecretStr | None = None
    base_url: str | None = Field(default=None, max_length=500)
    models: list[ModelCreate] = Field(default_factory=list, max_length=MAX_MODELS_PER_REQUEST)
    enabled: bool = True

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _validate_display_name(value)

    @field_validator("api_key")
    @classmethod
    def _key(cls, value: SecretStr | None) -> SecretStr | None:
        return _validate_api_key(value)

    @field_validator("base_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return strip_or_none(value)

    @model_validator(mode="after")
    def _unique_models(self) -> "ProviderCreate":
        ids = [m.model_identifier for m in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError("Each model can be added only once.")
        return self


class ProviderUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    # Send null to go back to the provider's default URL.
    base_url: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _validate_display_name(value)

    @field_validator("base_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return strip_or_none(value)


class KeyReplace(BaseModel):
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def _key(cls, value: SecretStr) -> SecretStr:
        checked = _validate_api_key(value)
        if checked is None:
            raise ValueError("Enter the new API key.")
        return checked


class ProviderOut(BaseModel):
    id: uuid.UUID
    provider_type: ProviderType
    provider_label: str
    display_name: str
    base_url: str | None
    effective_base_url: str
    enabled: bool
    has_key: bool
    key_masked: str | None
    key_updated_at: datetime | None
    health_state: str
    consecutive_failures: int
    last_error_class: str | None
    last_error_message: str | None
    last_error_at: datetime | None
    last_success_at: datetime | None
    last_tested_at: datetime | None
    verification: Literal["mocked", "live"]
    models: list[ModelOut]
    created_at: datetime
    updated_at: datetime


# --- connection tests & discovery -------------------------------------------------------


class ConnectionTestIn(BaseModel):
    model_id: uuid.UUID | None = None
    model_identifier: str | None = Field(default=None, max_length=200)

    @field_validator("model_identifier")
    @classmethod
    def _mid(cls, value: str | None) -> str | None:
        value = strip_or_none(value)
        return None if value is None else _validate_model_identifier(value)


class ConnectionTestOut(BaseModel):
    ok: bool
    provider_id: uuid.UUID
    model_identifier: str
    latency_ms: int
    error_class: str | None = None
    error_hint: str | None = None
    message: str
    http_status: int | None = None
    health_state: str
    tested_at: datetime


class DiscoveredModelOut(BaseModel):
    id: str
    display_name: str | None
    context_window: int | None
    configured: bool


class DiscoveredModelsOut(BaseModel):
    ok: bool
    models: list[DiscoveredModelOut]
    error_class: str | None = None
    message: str | None = None


# --- routing ----------------------------------------------------------------------------


class RouteEntryOut(BaseModel):
    position: int
    model_id: uuid.UUID
    model_identifier: str
    model_display_name: str | None
    provider_id: uuid.UUID
    provider_name: str
    provider_type: ProviderType
    available: bool
    unavailable_reason: str | None
    health_state: str


class RoleRouteOut(BaseModel):
    role: ModelRole
    uses_default: bool  # no chain of its own; the 'default' chain applies
    entries: list[RouteEntryOut]


class RoutesOut(BaseModel):
    roles: list[RoleRouteOut]


class RouteUpdate(BaseModel):
    model_ids: list[uuid.UUID] = Field(max_length=MAX_CHAIN_LENGTH)

    @field_validator("model_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("A model can appear only once in a chain.")
        return value


class RoutingPolicyOut(BaseModel):
    max_retries: int
    max_retry_after_seconds: int
    fallback_on_rate_limit: bool
    fallback_on_quota_exhausted: bool


class RoutingPolicyUpdate(BaseModel):
    max_retries: int | None = Field(default=None, ge=0, le=5)
    max_retry_after_seconds: int | None = Field(default=None, ge=0, le=120)
    fallback_on_rate_limit: bool | None = None
    fallback_on_quota_exhausted: bool | None = None


class AttemptOut(BaseModel):
    provider_name: str
    model_identifier: str
    model_id: uuid.UUID | None
    outcome: str
    attempt: int | None
    error_class: str | None
    message: str | None
    http_status: int | None
    latency_ms: int | None


class RoutingTestOut(BaseModel):
    ok: bool
    role: ModelRole
    provider_name: str | None = None
    model_identifier: str | None = None
    latency_ms: int | None = None
    used_fallback: bool = False
    error_code: str | None = None
    error_class: str | None = None
    message: str | None = None
    attempts: list[AttemptOut]


# --- health & usage ---------------------------------------------------------------------


class ProviderHealthOut(BaseModel):
    provider_id: uuid.UUID
    display_name: str
    provider_type: ProviderType
    enabled: bool
    health_state: str
    last_error_class: str | None
    last_error_message: str | None
    last_error_at: datetime | None
    last_success_at: datetime | None
    last_tested_at: datetime | None
    window_hours: int
    calls: int
    successes: int
    failures: int
    success_rate: float | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None


class HealthSummaryOut(BaseModel):
    window_hours: int
    providers: list[ProviderHealthOut]


UsageGroupBy = Literal["provider", "model", "day", "purpose", "outcome"]


class UsageRowOut(BaseModel):
    key: str
    label: str
    calls: int
    successes: int
    failures: int
    input_tokens: int
    output_tokens: int
    est_cost_usd: Decimal | None
    avg_latency_ms: float | None


class UsageSummaryOut(BaseModel):
    date_from: datetime
    date_to: datetime
    group_by: UsageGroupBy
    rows: list[UsageRowOut]
    totals: UsageRowOut


class UsageRecordOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    call_id: uuid.UUID
    provider_id: uuid.UUID | None
    provider_name: str
    provider_type: str
    model_identifier: str
    role: str
    purpose: str
    attempt: int
    outcome: str
    error_class: str | None
    http_status: int | None
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    est_cost_usd: Decimal | None

    model_config = {"from_attributes": True}
