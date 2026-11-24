"""Password hashing and session token primitives."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import bcrypt
import jwt

from app.core.config import Settings

BCRYPT_ROUNDS = 12
# bcrypt only uses the first 72 bytes of input; we reject longer passwords at the
# schema layer so that two different long passwords can never collide.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str, rounds: int = BCRYPT_ROUNDS) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


@lru_cache(maxsize=4)
def _dummy_hash(rounds: int) -> str:
    return hash_password("timing-equaliser-not-a-real-password", rounds=rounds)


def verify_dummy_password(password: str, rounds: int = BCRYPT_ROUNDS) -> None:
    """Spend the same time as a real check when the account does not exist."""
    verify_password(password, _dummy_hash(rounds))


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    token_version: int
    expires_at: datetime


def create_access_token(
    settings: Settings, user_id: uuid.UUID, token_version: int
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "typ": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(settings: Settings, token: str) -> TokenClaims | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat", "ver"]},
        )
        if payload.get("typ") != "access":
            return None
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            token_version=int(payload["ver"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError):
        return None
