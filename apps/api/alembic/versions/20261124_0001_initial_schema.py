"""Initial schema: users, projects, research_tasks, audit_events

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_STATUSES = (
    "draft",
    "planning",
    "awaiting_approval",
    "approved",
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        *TASK_STATUSES, name="research_task_status_enum", create_type=False
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_projects_owner_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_index(
        "uq_projects_owner_name_lower",
        "projects",
        ["owner_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "research_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", status_enum, server_default="draft", nullable=False),
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_research_tasks_owner_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_research_tasks_project_id_projects",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_research_tasks"),
    )
    op.create_index("ix_research_tasks_project_id", "research_tasks", ["project_id"])
    op.create_index("ix_research_tasks_owner_status", "research_tasks", ["owner_id", "status"])
    op.create_index("ix_research_tasks_owner_updated", "research_tasks", ["owner_id", "updated_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("data", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_events_actor_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])
    op.create_index("ix_audit_events_actor_created", "audit_events", ["actor_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("research_tasks")
    op.drop_table("projects")
    op.drop_table("users")
    postgresql.ENUM(name="research_task_status_enum").drop(op.get_bind(), checkfirst=True)
