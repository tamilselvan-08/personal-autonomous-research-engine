from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.errors import UnauthenticatedError
from app.core.logging import user_id_var
from app.core.security import decode_access_token
from app.models import User
from app.schemas.common import PaginationParams

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def _extract_token(request: Request, settings: Settings) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(settings.session_cookie_name)


def get_current_user(request: Request, db: DbSession, settings: AppSettings) -> User:
    token = _extract_token(request, settings)
    if not token:
        raise UnauthenticatedError("Authentication required.")
    claims = decode_access_token(settings, token)
    if claims is None:
        raise UnauthenticatedError("Your session is invalid or has expired. Please sign in again.")
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active or user.token_version != claims.token_version:
        raise UnauthenticatedError("Your session is no longer valid. Please sign in again.")
    user_id_var.set(str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def pagination(
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 20,
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)


Pagination = Annotated[PaginationParams, Depends(pagination)]
