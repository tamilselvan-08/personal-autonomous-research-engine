"""Application configuration loaded from environment variables.

All settings come from the environment (or a local `.env` file in development).
Secrets are never given defaults that would work in production.
"""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

APP_VERSION = "0.2.0"

_PLACEHOLDER_SECRETS = {"change-me", "changeme", "replace-me", "CHANGE_ME_TO_A_LONG_RANDOM_STRING"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "PARE"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    database_url: str = Field(
        default="postgresql+psycopg://pare:pare@localhost:5432/pare",
        description="SQLAlchemy URL. Use the psycopg (v3) driver.",
    )
    database_echo: bool = False

    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_ttl_minutes: int = Field(default=720, ge=5, le=60 * 24 * 7)

    session_cookie_name: str = "pare_session"
    session_cookie_secure: bool = False  # True when served over HTTPS

    # NoDecode: accept comma-separated env values ("a,b") as well as JSON lists.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    allowed_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1", "api", "testserver"]

    bcrypt_rounds: int = Field(default=12, ge=4, le=15)

    allow_registration: bool = True
    login_rate_limit_per_minute: int = Field(default=10, ge=1)

    # --- Credential encryption (AI provider API keys) -------------------------------
    # Key-encryption key (KEK): 32 random bytes, base64/base64url encoded. Kept only in the
    # environment, never in the database. Without it, provider features are unavailable.
    secrets_master_key: SecretStr | None = None
    secrets_master_key_id: str = Field(default="k1", pattern=r"^[A-Za-z0-9_\-]{1,32}$")
    # Previous KEKs kept for decryption during rotation: "k1:<base64>,k0:<base64>".
    secrets_previous_keys: SecretStr | None = None

    # --- AI provider calls ------------------------------------------------------------
    ai_request_timeout_seconds: float = Field(default=60.0, ge=1, le=600)
    ai_connection_test_timeout_seconds: float = Field(default=20.0, ge=1, le=120)
    ai_connection_test_rate_limit_per_minute: int = Field(default=6, ge=1)

    public_api_base_url: str = "http://localhost:8000"
    default_timezone: str = "UTC"

    @field_validator("jwt_secret")
    @classmethod
    def _reject_placeholder_secret(cls, value: str) -> str:
        if value.strip() in _PLACEHOLDER_SECRETS:
            raise ValueError(
                "JWT_SECRET is still the placeholder value. Run scripts/setup-env "
                "or set a random string of at least 32 characters."
            )
        return value

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
