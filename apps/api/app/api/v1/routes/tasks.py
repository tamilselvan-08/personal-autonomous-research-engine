import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession, Pagination
from app.models import TaskStatus
from app.schemas.common import ErrorResponse, Page
from app.schemas.task import (
    ActivityOut,
    TaskCreate,
    TaskOut,
    TaskSort,
    TaskStats,
    TaskStatusOut,
    TaskUpdate,
)
from app.services import audit_service, task_service

router = APIRouter(
    prefix="/tasks",
    tags=["research tasks"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)


@router.get("", response_model=Page[TaskOut], summary="List research tasks")
def list_tasks(
    user: CurrentUser,
    db: DbSession,
    pagination: Pagination,
    q: Annotated[
        str | None, Query(max_length=200, description="Search title and objective")
    ] = None,
    status_filter: Annotated[
        list[TaskStatus] | None, Query(alias="status", description="Repeat to filter by several")
    ] = None,
    project_id: uuid.UUID | None = None,
    sort: TaskSort = TaskSort.UPDATED_DESC,
) -> Page[TaskOut]:
    return task_service.list_tasks(
        db, user.id, pagination, q=q, statuses=status_filter, project_id=project_id, sort=sort
    )


@router.get("/stats", response_model=TaskStats, summary="Task counts for the dashboard")
def task_stats(user: CurrentUser, db: DbSession) -> TaskStats:
    return task_service.stats(db, user.id)


@router.get(
    "/recent-activity", response_model=list[ActivityOut], summary="Recent task and project activity"
)
def recent_activity(
    user: CurrentUser, db: DbSession, limit: Annotated[int, Query(ge=1, le=50)] = 10
) -> list[ActivityOut]:
    return [
        ActivityOut.model_validate(e) for e in audit_service.recent_for_actor(db, user.id, limit)
    ]


@router.post(
    "",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": ErrorResponse}},
    summary="Create a draft research task",
)
def create_task(data: TaskCreate, user: CurrentUser, db: DbSession) -> TaskOut:
    return task_service.create_task(db, user.id, data)


@router.get("/{task_id}", response_model=TaskOut, summary="Get a research task")
def get_task(task_id: uuid.UUID, user: CurrentUser, db: DbSession) -> TaskOut:
    return task_service.get_task(db, user.id, task_id)


@router.get("/{task_id}/status", response_model=TaskStatusOut, summary="Task status")
def get_task_status(task_id: uuid.UUID, user: CurrentUser, db: DbSession) -> TaskStatusOut:
    return task_service.get_status(db, user.id, task_id)


@router.patch(
    "/{task_id}",
    response_model=TaskOut,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    summary="Edit a draft research task",
)
def update_task(task_id: uuid.UUID, data: TaskUpdate, user: CurrentUser, db: DbSession) -> TaskOut:
    return task_service.update_task(db, user.id, task_id, data)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorResponse}},
    summary="Delete a research task",
)
def delete_task(task_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    task_service.delete_task(db, user.id, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
