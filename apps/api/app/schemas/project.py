import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel, strip_or_none


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value

    @field_validator("description")
    @classmethod
    def _desc(cls, value: str | None) -> str | None:
        return strip_or_none(value)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank.")
        return value

    @field_validator("description")
    @classmethod
    def _desc(cls, value: str | None) -> str | None:
        return strip_or_none(value)


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    task_count: int = 0
    created_at: datetime
    updated_at: datetime


class ProjectSummary(ORMModel):
    id: uuid.UUID
    name: str
