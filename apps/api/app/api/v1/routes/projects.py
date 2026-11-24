import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession, Pagination
from app.schemas.common import ErrorResponse, Page
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import project_service

router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)


@router.get("", response_model=Page[ProjectOut], summary="List projects")
def list_projects(
    user: CurrentUser,
    db: DbSession,
    pagination: Pagination,
    q: Annotated[str | None, Query(max_length=200, description="Filter by name")] = None,
) -> Page[ProjectOut]:
    return project_service.list_projects(db, user.id, pagination, q)


@router.post(
    "",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
    summary="Create a project",
)
def create_project(data: ProjectCreate, user: CurrentUser, db: DbSession) -> ProjectOut:
    return project_service.create_project(db, user.id, data)


@router.get("/{project_id}", response_model=ProjectOut, summary="Get a project")
def get_project(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProjectOut:
    return project_service.get_project(db, user.id, project_id)


@router.patch(
    "/{project_id}",
    response_model=ProjectOut,
    responses={409: {"model": ErrorResponse}},
    summary="Update a project",
)
def update_project(
    project_id: uuid.UUID, data: ProjectUpdate, user: CurrentUser, db: DbSession
) -> ProjectOut:
    return project_service.update_project(db, user.id, project_id, data)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorResponse}},
    summary="Delete a project",
)
def delete_project(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    detach_tasks: Annotated[
        bool, Query(description="Unassign this project's tasks instead of refusing")
    ] = False,
) -> Response:
    project_service.delete_project(db, user.id, project_id, detach_tasks=detach_tasks)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
