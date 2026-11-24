import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.enums import TaskStatus
from app.schemas.common import ORMModel, strip_or_none
from app.schemas.project import ProjectSummary

TITLE_MAX = 200
OBJECTIVE_MIN = 10
OBJECTIVE_MAX = 5000
DESCRIPTION_MAX = 10000


def _clean_title(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Title is required.")
    return value


def _clean_objective(value: str) -> str:
    value = value.strip()
    if len(value) < OBJECTIVE_MIN:
        raise ValueError(f"Objective must be at least {OBJECTIVE_MIN} characters.")
    return value


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    objective: str = Field(min_length=OBJECTIVE_MIN, max_length=OBJECTIVE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    project_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return _clean_title(v)

    @field_validator("objective")
    @classmethod
    def _objective(cls, v: str) -> str:
        return _clean_objective(v)

    @field_validator("description")
    @classmethod
    def _description(cls, v: str | None) -> str | None:
        return strip_or_none(v)


class TaskUpdate(BaseModel):
    """Partial update. Send ``project_id: null`` to unassign the project."""

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    objective: str | None = Field(default=None, min_length=OBJECTIVE_MIN, max_length=OBJECTIVE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    project_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return None if v is None else _clean_title(v)

    @field_validator("objective")
    @classmethod
    def _objective(cls, v: str | None) -> str | None:
        return None if v is None else _clean_objective(v)

    @field_validator("description")
    @classmethod
    def _description(cls, v: str | None) -> str | None:
        return strip_or_none(v)


class TaskOut(ORMModel):
    id: uuid.UUID
    title: str
    objective: str
    description: str | None
    status: TaskStatus
    project_id: uuid.UUID | None
    project: ProjectSummary | None
    status_changed_at: datetime
    created_at: datetime
    updated_at: datetime
    is_editable: bool
    is_deletable: bool


class TaskStatusOut(BaseModel):
    id: uuid.UUID
    status: TaskStatus
    status_changed_at: datetime
    allowed_transitions: list[TaskStatus]


class TaskStats(BaseModel):
    total: int
    by_status: dict[TaskStatus, int]
    active: int
    completed: int
    failed: int


class TaskSort(StrEnum):
    UPDATED_DESC = "updated_desc"
    CREATED_DESC = "created_desc"
    CREATED_ASC = "created_asc"
    TITLE_ASC = "title_asc"


class ActivityOut(ORMModel):
    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    data: dict[str, Any]
    created_at: datetime
