import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import MAX_PASSWORD_BYTES
from app.schemas.common import ORMModel


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str
    created_at: datetime


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def _password_rules(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
        if value.strip() != value:
            raise ValueError("Password must not start or end with whitespace.")
        if value.isdigit() or value.isalpha():
            raise ValueError("Password must mix letters with numbers or symbols.")
        return value

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Display name is required.")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_at: datetime
