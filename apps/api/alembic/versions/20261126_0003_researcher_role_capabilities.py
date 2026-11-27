"""Add the 'researcher' model role and model capabilities.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of the role values before and after this migration.
OLD_ROLES = ("default", "planner", "extractor", "verifier", "summarizer")
NEW_ROLES = ("default", "planner", "researcher", "extractor", "verifier", "summarizer")
ROLE_CONSTRAINTS = (
    ("model_routes", "ck_model_routes_role"),
    ("usage_records", "ck_usage_records_role"),
)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    for table, name in ROLE_CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, _in("role", NEW_ROLES))

    op.add_column(
        "ai_models",
        sa.Column(
            "capabilities",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_ai_models_capabilities", "ai_models", "jsonb_typeof(capabilities) = 'array'"
    )


def downgrade() -> None:
    op.drop_constraint("ck_ai_models_capabilities", "ai_models", type_="check")
    op.drop_column("ai_models", "capabilities")

    # Rows using the new role cannot satisfy the old constraint: remove the researcher
    # chain, and re-label its usage history as 'default' (history is kept, not deleted).
    op.execute("DELETE FROM model_routes WHERE role = 'researcher'")
    op.execute("UPDATE usage_records SET role = 'default' WHERE role = 'researcher'")
    for table, name in ROLE_CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, _in("role", OLD_ROLES))
