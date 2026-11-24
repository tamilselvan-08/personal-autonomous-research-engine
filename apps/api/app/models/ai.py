"""AI provider configuration, encrypted credentials, routing and usage.

String columns with CHECK constraints are used instead of PostgreSQL enum types so that
adding a provider type or health state is a one-line constraint change in a migration.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    HealthState,
    ModelRole,
    ProviderType,
    SecretKind,
    UsageOutcome,
    UsagePurpose,
)


def check_in(column: str, enum_cls: type[enum.StrEnum]) -> str:
    values = ", ".join(f"'{m.value}'" for m in enum_cls)
    return f"{column} IN ({values})"


class Secret(UUIDPrimaryKeyMixin, Base):
    """An encrypted credential. Never serialised by any API response."""

    __tablename__ = "secrets"
    __table_args__ = (CheckConstraint(check_in("kind", SecretKind), name="kind"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kek_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # never include key material
        return f"<Secret id={self.id} kind={self.kind} kek_id={self.kek_id}>"


class HealthColumnsMixin:
    health_state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=HealthState.UNKNOWN.value
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_error_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIProvider(UUIDPrimaryKeyMixin, TimestampMixin, HealthColumnsMixin, Base):
    __tablename__ = "ai_providers"
    __table_args__ = (
        Index(
            "uq_ai_providers_owner_name_lower",
            "owner_id",
            func.lower(text("display_name")),
            unique=True,
        ),
        CheckConstraint(check_in("provider_type", ProviderType), name="provider_type"),
        CheckConstraint(check_in("health_state", HealthState), name="health_state"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("secrets.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    secret: Mapped[Secret | None] = relationship(lazy="joined")
    models: Mapped[list["AIModel"]] = relationship(
        back_populates="provider",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AIModel.created_at",
        lazy="selectin",
    )


class AIModel(UUIDPrimaryKeyMixin, TimestampMixin, HealthColumnsMixin, Base):
    __tablename__ = "ai_models"
    __table_args__ = (
        UniqueConstraint("provider_id", "model_identifier", name="uq_ai_models_provider_model"),
        CheckConstraint(check_in("health_state", HealthState), name="health_state"),
        CheckConstraint(
            "input_price_per_mtok IS NULL OR input_price_per_mtok >= 0", name="input_price"
        ),
        CheckConstraint(
            "output_price_per_mtok IS NULL OR output_price_per_mtok >= 0", name="output_price"
        ),
        CheckConstraint("context_window IS NULL OR context_window > 0", name="context_window"),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised from the provider so every query can be scoped by owner directly.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    output_price_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    supports_json: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Circuit breaker: opened after repeated transient failures; half-open after a cool-down.
    circuit_opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    provider: Mapped[AIProvider] = relationship(back_populates="models", lazy="joined")


class ModelRoute(UUIDPrimaryKeyMixin, Base):
    """One entry in a role's ordered chain. Position 0 is the primary model."""

    __tablename__ = "model_routes"
    __table_args__ = (
        UniqueConstraint("owner_id", "role", "position", name="uq_model_routes_owner_role_pos"),
        UniqueConstraint("owner_id", "role", "model_id", name="uq_model_routes_owner_role_model"),
        CheckConstraint(check_in("role", ModelRole), name="role"),
        CheckConstraint("position >= 0", name="position"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    model: Mapped[AIModel] = relationship(lazy="joined")


class RoutingPolicy(TimestampMixin, Base):
    """Per-user retry and fallback preferences. A missing row means the defaults."""

    __tablename__ = "ai_routing_policies"
    __table_args__ = (
        CheckConstraint("max_retries BETWEEN 0 AND 5", name="max_retries"),
        CheckConstraint("max_retry_after_seconds BETWEEN 0 AND 120", name="max_retry_after"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    max_retries: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="2")
    max_retry_after_seconds: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="20"
    )
    fallback_on_rate_limit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    fallback_on_quota_exhausted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class UsageRecord(UUIDPrimaryKeyMixin, Base):
    """One row per provider attempt. Contains no prompt or response content."""

    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_owner_created", "owner_id", "created_at"),
        Index("ix_usage_records_provider_created", "provider_id", "created_at"),
        Index("ix_usage_records_model_created", "model_id", "created_at"),
        CheckConstraint(check_in("outcome", UsageOutcome), name="outcome"),
        CheckConstraint(check_in("purpose", UsagePurpose), name="purpose"),
        CheckConstraint(check_in("role", ModelRole), name="role"),
        CheckConstraint("attempt >= 1", name="attempt"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_providers.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_models.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshots so history stays readable after a provider or model is deleted.
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    # Groups the attempts of one routed call (primary, retries, fallbacks).
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    http_status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 8), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
