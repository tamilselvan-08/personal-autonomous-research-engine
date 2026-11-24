import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    data: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit event to the current transaction (caller commits)."""
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        data=data or {},
    )
    db.add(event)
    return event


def recent_for_actor(
    db: Session,
    actor_id: uuid.UUID,
    limit: int = 10,
    entity_types: tuple[str, ...] = ("research_task", "project"),
) -> list[AuditEvent]:
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.actor_id == actor_id, AuditEvent.entity_type.in_(entity_types))
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        .limit(limit)
    )
    return list(db.scalars(stmt))
