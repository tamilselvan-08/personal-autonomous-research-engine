"""AI providers: secrets, ai_providers, ai_models, model_routes, ai_routing_policies,
usage_records

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of the enum values at the time of this migration. Later migrations that add
# values must drop and recreate the CHECK constraint.
PROVIDER_TYPES = (
    "openai",
    "gemini",
    "anthropic",
    "xai",
    "deepseek",
    "mistral",
    "openai_compatible",
)
HEALTH_STATES = (
    "unknown",
    "healthy",
    "degraded",
    "down",
    "invalid_credentials",
    "quota_exhausted",
    "misconfigured",
)
ROLES = ("default", "planner", "extractor", "verifier", "summarizer")
OUTCOMES = ("success", "retry", "fallback", "error")
PURPOSES = ("completion", "connection_test", "routing_test")
SECRET_KINDS = ("llm_api_key",)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _ts(name: str, nullable: bool = False) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _health_columns() -> list[sa.Column]:
    return [
        sa.Column("health_state", sa.String(32), server_default="unknown", nullable=False),
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_error_class", sa.String(40), nullable=True),
        sa.Column("last_error_message", sa.String(500), nullable=True),
        _ts("last_error_at", nullable=True),
        _ts("last_success_at", nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "secrets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("dek_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("kek_id", sa.String(32), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        _ts("created_at"),
        _ts("rotated_at", nullable=True),
        sa.CheckConstraint(_in("kind", SECRET_KINDS), name="ck_secrets_kind"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_secrets_owner_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_secrets"),
    )
    op.create_index("ix_secrets_owner_id", "secrets", ["owner_id"])
    op.create_index("ix_secrets_kek_id", "secrets", ["kek_id"])

    op.create_table(
        "ai_providers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=True),
        sa.Column("secret_id", sa.UUID(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _ts("last_tested_at", nullable=True),
        *_health_columns(),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            _in("provider_type", PROVIDER_TYPES), name="ck_ai_providers_provider_type"
        ),
        sa.CheckConstraint(_in("health_state", HEALTH_STATES), name="ck_ai_providers_health_state"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_ai_providers_owner_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["secret_id"],
            ["secrets.id"],
            name="fk_ai_providers_secret_id_secrets",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_providers"),
    )
    op.create_index("ix_ai_providers_owner_id", "ai_providers", ["owner_id"])
    op.create_index(
        "uq_ai_providers_owner_name_lower",
        "ai_providers",
        ["owner_id", sa.text("lower(display_name)")],
        unique=True,
    )

    op.create_table(
        "ai_models",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("model_identifier", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("input_price_per_mtok", sa.Numeric(12, 6), nullable=True),
        sa.Column("output_price_per_mtok", sa.Numeric(12, 6), nullable=True),
        sa.Column("supports_json", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _ts("circuit_opened_at", nullable=True),
        *_health_columns(),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(_in("health_state", HEALTH_STATES), name="ck_ai_models_health_state"),
        sa.CheckConstraint(
            "input_price_per_mtok IS NULL OR input_price_per_mtok >= 0",
            name="ck_ai_models_input_price",
        ),
        sa.CheckConstraint(
            "output_price_per_mtok IS NULL OR output_price_per_mtok >= 0",
            name="ck_ai_models_output_price",
        ),
        sa.CheckConstraint(
            "context_window IS NULL OR context_window > 0", name="ck_ai_models_context_window"
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["ai_providers.id"],
            name="fk_ai_models_provider_id_ai_providers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_ai_models_owner_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_models"),
        sa.UniqueConstraint("provider_id", "model_identifier", name="uq_ai_models_provider_model"),
    )
    op.create_index("ix_ai_models_owner_id", "ai_models", ["owner_id"])

    op.create_table(
        "model_routes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("model_id", sa.UUID(), nullable=False),
        _ts("created_at"),
        sa.CheckConstraint(_in("role", ROLES), name="ck_model_routes_role"),
        sa.CheckConstraint("position >= 0", name="ck_model_routes_position"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_model_routes_owner_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["ai_models.id"],
            name="fk_model_routes_model_id_ai_models",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_routes"),
        sa.UniqueConstraint("owner_id", "role", "position", name="uq_model_routes_owner_role_pos"),
        sa.UniqueConstraint(
            "owner_id", "role", "model_id", name="uq_model_routes_owner_role_model"
        ),
    )
    op.create_index("ix_model_routes_model_id", "model_routes", ["model_id"])

    op.create_table(
        "ai_routing_policies",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("max_retries", sa.SmallInteger(), server_default="2", nullable=False),
        sa.Column(
            "max_retry_after_seconds", sa.SmallInteger(), server_default="20", nullable=False
        ),
        sa.Column(
            "fallback_on_rate_limit", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "fallback_on_quota_exhausted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "max_retries BETWEEN 0 AND 5", name="ck_ai_routing_policies_max_retries"
        ),
        sa.CheckConstraint(
            "max_retry_after_seconds BETWEEN 0 AND 120",
            name="ck_ai_routing_policies_max_retry_after",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_ai_routing_policies_owner_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("owner_id", name="pk_ai_routing_policies"),
    )

    op.create_table(
        "usage_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("provider_id", sa.UUID(), nullable=True),
        sa.Column("model_id", sa.UUID(), nullable=True),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("provider_name", sa.String(100), nullable=False),
        sa.Column("model_identifier", sa.String(200), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("attempt", sa.SmallInteger(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("error_class", sa.String(40), nullable=True),
        sa.Column("http_status", sa.SmallInteger(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("est_cost_usd", sa.Numeric(14, 8), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(_in("outcome", OUTCOMES), name="ck_usage_records_outcome"),
        sa.CheckConstraint(_in("purpose", PURPOSES), name="ck_usage_records_purpose"),
        sa.CheckConstraint(_in("role", ROLES), name="ck_usage_records_role"),
        sa.CheckConstraint("attempt >= 1", name="ck_usage_records_attempt"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_usage_records_owner_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["ai_providers.id"],
            name="fk_usage_records_provider_id_ai_providers",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["ai_models.id"],
            name="fk_usage_records_model_id_ai_models",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_usage_records"),
    )
    op.create_index("ix_usage_records_owner_created", "usage_records", ["owner_id", "created_at"])
    op.create_index(
        "ix_usage_records_provider_created", "usage_records", ["provider_id", "created_at"]
    )
    op.create_index("ix_usage_records_model_created", "usage_records", ["model_id", "created_at"])
    op.create_index("ix_usage_records_call_id", "usage_records", ["call_id"])


def downgrade() -> None:
    op.drop_table("usage_records")
    op.drop_table("ai_routing_policies")
    op.drop_table("model_routes")
    op.drop_table("ai_models")
    op.drop_table("ai_providers")
    op.drop_table("secrets")
