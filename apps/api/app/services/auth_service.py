import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, ForbiddenError, UnauthenticatedError
from app.core.security import (
    create_access_token,
    hash_password,
    verify_dummy_password,
    verify_password,
)
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services import audit_service

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Incorrect email or password."


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))


def register(db: Session, settings: Settings, data: RegisterRequest) -> User:
    if not settings.allow_registration:
        raise ForbiddenError(
            "Registration is disabled on this installation.", code="REGISTRATION_DISABLED"
        )
    email = normalize_email(data.email)
    if get_by_email(db, email):
        raise ConflictError("An account with this email already exists.", code="EMAIL_TAKEN")
    user = User(
        email=email,
        display_name=data.display_name,
        password_hash=hash_password(data.password, rounds=settings.bcrypt_rounds),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent registration with the same email
        db.rollback()
        raise ConflictError(
            "An account with this email already exists.", code="EMAIL_TAKEN"
        ) from exc
    audit_service.record(
        db, actor_id=user.id, action="user.registered", entity_type="user", entity_id=user.id
    )
    db.commit()
    logger.info("User registered", extra={"user_id": str(user.id)})
    return user


def authenticate(db: Session, settings: Settings, data: LoginRequest) -> User:
    user = get_by_email(db, data.email)
    if user is None:
        verify_dummy_password(data.password, rounds=settings.bcrypt_rounds)
        raise UnauthenticatedError(INVALID_CREDENTIALS, code="INVALID_CREDENTIALS")
    if not verify_password(data.password, user.password_hash) or not user.is_active:
        raise UnauthenticatedError(INVALID_CREDENTIALS, code="INVALID_CREDENTIALS")
    user.last_login_at = datetime.now(UTC)
    audit_service.record(
        db, actor_id=user.id, action="user.logged_in", entity_type="user", entity_id=user.id
    )
    db.commit()
    return user


def issue_token(settings: Settings, user: User) -> tuple[str, datetime]:
    return create_access_token(settings, user.id, user.token_version)
