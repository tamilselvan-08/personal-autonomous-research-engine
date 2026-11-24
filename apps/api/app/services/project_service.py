import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models import Project, ResearchTask
from app.schemas.common import Page, PaginationParams, make_page
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import audit_service

NAME_TAKEN = "A project with this name already exists."


def _task_count_subquery():  # type: ignore[no-untyped-def]
    return (
        select(func.count(ResearchTask.id))
        .where(ResearchTask.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )


def _to_out(project: Project, task_count: int) -> ProjectOut:
    out = ProjectOut.model_validate(project)
    out.task_count = task_count
    return out


def get_owned(db: Session, owner_id: uuid.UUID, project_id: uuid.UUID) -> Project:
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
    )
    if project is None:
        raise NotFoundError("Project not found.")
    return project


def _name_exists(
    db: Session, owner_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> bool:
    stmt = select(Project.id).where(
        Project.owner_id == owner_id, func.lower(Project.name) == name.lower()
    )
    if exclude_id:
        stmt = stmt.where(Project.id != exclude_id)
    return db.scalar(stmt) is not None


def _count_tasks(db: Session, project_id: uuid.UUID) -> int:
    return (
        db.scalar(select(func.count(ResearchTask.id)).where(ResearchTask.project_id == project_id))
        or 0
    )


def list_projects(
    db: Session, owner_id: uuid.UUID, params: PaginationParams, q: str | None = None
) -> Page[ProjectOut]:
    base = select(Project).where(Project.owner_id == owner_id)
    if q and q.strip():
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        base = base.where(Project.name.ilike(f"%{term}%", escape="\\"))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.add_columns(_task_count_subquery().label("task_count"))
        .order_by(func.lower(Project.name), Project.id)
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return make_page([_to_out(p, c) for p, c in rows], total, params)


def get_project(db: Session, owner_id: uuid.UUID, project_id: uuid.UUID) -> ProjectOut:
    project = get_owned(db, owner_id, project_id)
    return _to_out(project, _count_tasks(db, project.id))


def create_project(db: Session, owner_id: uuid.UUID, data: ProjectCreate) -> ProjectOut:
    if _name_exists(db, owner_id, data.name):
        raise ConflictError(NAME_TAKEN, code="PROJECT_NAME_TAKEN")
    project = Project(owner_id=owner_id, name=data.name, description=data.description)
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(NAME_TAKEN, code="PROJECT_NAME_TAKEN") from exc
    audit_service.record(
        db,
        actor_id=owner_id,
        action="project.created",
        entity_type="project",
        entity_id=project.id,
        data={"name": project.name},
    )
    db.commit()
    return _to_out(project, 0)


def update_project(
    db: Session, owner_id: uuid.UUID, project_id: uuid.UUID, data: ProjectUpdate
) -> ProjectOut:
    project = get_owned(db, owner_id, project_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        changes.pop("name")
    if "name" in changes and _name_exists(db, owner_id, changes["name"], exclude_id=project.id):
        raise ConflictError(NAME_TAKEN, code="PROJECT_NAME_TAKEN")
    for field, value in changes.items():
        setattr(project, field, value)
    if changes:
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise ConflictError(NAME_TAKEN, code="PROJECT_NAME_TAKEN") from exc
        audit_service.record(
            db,
            actor_id=owner_id,
            action="project.updated",
            entity_type="project",
            entity_id=project.id,
            data={"fields": sorted(changes)},
        )
        db.commit()
        db.refresh(project)
    return _to_out(project, _count_tasks(db, project.id))


def delete_project(
    db: Session, owner_id: uuid.UUID, project_id: uuid.UUID, *, detach_tasks: bool
) -> None:
    project = get_owned(db, owner_id, project_id)
    task_count = _count_tasks(db, project.id)
    if task_count and not detach_tasks:
        raise ConflictError(
            f"This project has {task_count} research task(s). Move them first or delete with "
            "detach_tasks=true to unassign them.",
            code="PROJECT_HAS_TASKS",
            details={"task_count": task_count},
        )
    if task_count:
        db.execute(
            update(ResearchTask)
            .where(ResearchTask.project_id == project.id, ResearchTask.owner_id == owner_id)
            .values(project_id=None)
        )
    audit_service.record(
        db,
        actor_id=owner_id,
        action="project.deleted",
        entity_type="project",
        entity_id=project.id,
        data={"name": project.name, "detached_tasks": task_count},
    )
    db.delete(project)
    db.commit()
