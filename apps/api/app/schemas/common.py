from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def make_page[T](items: list[T], total: int, params: PaginationParams) -> Page[T]:
    pages = (total + params.page_size - 1) // params.page_size if total else 0
    return Page[T](
        items=items, total=total, page=params.page, page_size=params.page_size, pages=pages
    )


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


def strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
