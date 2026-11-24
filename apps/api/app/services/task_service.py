import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, FieldValidationError, NotFoundError
from app.domain import task_state
from app.models import Project, ResearchTask, TaskStatus
from app.repositories import task_repository
from app.schemas.common import Page, PaginationParams, make_page
from app.schemas.task import TaskCreate, TaskOut, TaskSort, TaskStats, TaskStatusOut, TaskUpdate
from app.services import audit_service

_NON_NULLABLE_UPDATE_FIELDS = {"title", "objective"}


def to_out(task: ResearchTask) -> TaskOut:
    return TaskOut.model_validate(
        {
            "id": task.id,
            "title": task.title,
            "objective": task.objective,
            "description": task.description,
            "status": task.status,
            "project_id": task.project_id,
            "project": task.project,
            "status_changed_at": task.status_changed_at,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "is_editable": task_state.is_editable(task.status),
            "is_deletable": task_state.is_deletable(task.status),
        }
    )


def _get_owned(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID) -> ResearchTask:
    task = task_repository.get(db, owner_id, task_id)
    if task is None:
        raise NotFoundError("Research task not found.")
    return task


def _validate_project(db: Session, owner_id: uuid.UUID, project_id: uuid.UUID | None) -> None:
    if project_id is None:
        return
    project = db.get(Project, project_id)
    if project is None or project.owner_id != owner_id:
        # 422 rather than 404: the task is fine, the reference is not.
        raise FieldValidationError("project_id", "Project does not exist.")


def list_tasks(
    db: Session,
    owner_id: uuid.UUID,
    params: PaginationParams,
    *,
    q: str | None = None,
    statuses: Sequence[TaskStatus] | None = None,
    project_id: uuid.UUID | None = None,
    sort: TaskSort = TaskSort.UPDATED_DESC,
) -> Page[TaskOut]:
    rows, total = task_repository.list_tasks(
        db,
        owner_id,
        q=q,
        statuses=statuses,
        project_id=project_id,
        sort=sort,
        offset=params.offset,
        limit=params.page_size,
    )
    return make_page([to_out(t) for t in rows], total, params)


def get_task(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID) -> TaskOut:
    return to_out(_get_owned(db, owner_id, task_id))


def get_status(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID) -> TaskStatusOut:
    task = _get_owned(db, owner_id, task_id)
    return TaskStatusOut(
        id=task.id,
        status=task.status,
        status_changed_at=task.status_changed_at,
        allowed_transitions=task_state.allowed_transitions(task.status),
    )


def create_task(db: Session, owner_id: uuid.UUID, data: TaskCreate) -> TaskOut:
    _validate_project(db, owner_id, data.project_id)
    task = ResearchTask(
        owner_id=owner_id,
        project_id=data.project_id,
        title=data.title,
        objective=data.objective,
        description=data.description,
        status=TaskStatus.DRAFT,
    )
    db.add(task)
    db.flush()
    audit_service.record(
        db,
        actor_id=owner_id,
        action="task.created",
        entity_type="research_task",
        entity_id=task.id,
        data={"title": task.title},
    )
    db.commit()
    db.refresh(task)
    return to_out(task)


def update_task(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID, data: TaskUpdate) -> TaskOut:
    task = _get_owned(db, owner_id, task_id)
    if not task_state.is_editable(task.status):
        raise ConflictError(
            "Only draft research tasks can be edited.",
            code="TASK_NOT_EDITABLE",
            details={"status": task.status.value},
        )
    changes = data.model_dump(exclude_unset=True)
    for field in _NON_NULLABLE_UPDATE_FIELDS:
        if field in changes and changes[field] is None:
            raise FieldValidationError(field, f"{field.capitalize()} cannot be empty.")
    if "project_id" in changes:
        _validate_project(db, owner_id, changes["project_id"])
    changed = [f for f, v in changes.items() if getattr(task, f) != v]
    for field in changed:
        setattr(task, field, changes[field])
    if changed:
        audit_service.record(
            db,
            actor_id=owner_id,
            action="task.updated",
            entity_type="research_task",
            entity_id=task.id,
            data={"title": task.title, "fields": sorted(changed)},
        )
        db.commit()
        db.refresh(task)
    return to_out(task)


def delete_task(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID) -> None:
    task = _get_owned(db, owner_id, task_id)
    if not task_state.is_deletable(task.status):
        raise ConflictError(
            f"A task that is {task.status.value.replace('_', ' ')} cannot be deleted. "
            "Cancel it first.",
            code="TASK_NOT_DELETABLE",
            details={"status": task.status.value},
        )
    audit_service.record(
        db,
        actor_id=owner_id,
        action="task.deleted",
        entity_type="research_task",
        entity_id=task.id,
        data={"title": task.title},
    )
    db.delete(task)
    db.commit()


def stats(db: Session, owner_id: uuid.UUID) -> TaskStats:
    counts = task_repository.count_by_status(db, owner_id)
    by_status = {s: counts.get(s, 0) for s in TaskStatus}
    return TaskStats(
        total=sum(by_status.values()),
        by_status=by_status,
        active=sum(by_status[s] for s in task_state.ACTIVE_STATUSES),
        completed=by_status[TaskStatus.COMPLETED],
        failed=by_status[TaskStatus.FAILED],
    )
