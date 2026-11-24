"""Query construction for research tasks.

Kept separate from the service because list filtering/sorting is the one place where
query building is non-trivial. Every function requires ``owner_id``: there is no
unscoped accessor by design (PRD SEC-110).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import ResearchTask, TaskStatus
from app.schemas.task import TaskSort


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered(
    owner_id: uuid.UUID,
    *,
    q: str | None,
    statuses: Sequence[TaskStatus] | None,
    project_id: uuid.UUID | None,
) -> Select[tuple[ResearchTask]]:
    stmt = select(ResearchTask).where(ResearchTask.owner_id == owner_id)
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(
                ResearchTask.title.ilike(pattern, escape="\\"),
                ResearchTask.objective.ilike(pattern, escape="\\"),
            )
        )
    if statuses:
        stmt = stmt.where(ResearchTask.status.in_(list(statuses)))
    if project_id:
        stmt = stmt.where(ResearchTask.project_id == project_id)
    return stmt


_SORTS = {
    TaskSort.UPDATED_DESC: (ResearchTask.updated_at.desc(), ResearchTask.id),
    TaskSort.CREATED_DESC: (ResearchTask.created_at.desc(), ResearchTask.id),
    TaskSort.CREATED_ASC: (ResearchTask.created_at.asc(), ResearchTask.id),
    TaskSort.TITLE_ASC: (func.lower(ResearchTask.title).asc(), ResearchTask.id),
}


def list_tasks(
    db: Session,
    owner_id: uuid.UUID,
    *,
    q: str | None,
    statuses: Sequence[TaskStatus] | None,
    project_id: uuid.UUID | None,
    sort: TaskSort,
    offset: int,
    limit: int,
) -> tuple[list[ResearchTask], int]:
    base = _filtered(owner_id, q=q, statuses=statuses, project_id=project_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(*_SORTS[sort]).offset(offset).limit(limit)).unique().all()
    return list(rows), total


def get(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID) -> ResearchTask | None:
    return db.scalar(
        select(ResearchTask).where(ResearchTask.id == task_id, ResearchTask.owner_id == owner_id)
    )


def count_by_status(db: Session, owner_id: uuid.UUID) -> dict[TaskStatus, int]:
    rows = db.execute(
        select(ResearchTask.status, func.count())
        .where(ResearchTask.owner_id == owner_id)
        .group_by(ResearchTask.status)
    ).all()
    return {status: count for status, count in rows}
