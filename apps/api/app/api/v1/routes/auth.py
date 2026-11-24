from fastapi import APIRouter, Request, Response, status

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.core.config import Settings
from app.core.errors import RateLimitedError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.schemas.auth import LoginRequest, LoginResponse, RegisterRequest, UserOut
from app.schemas.common import ErrorResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

_login_limiter: SlidingWindowRateLimiter | None = None


def get_login_limiter(settings: Settings) -> SlidingWindowRateLimiter:
    global _login_limiter
    if _login_limiter is None or _login_limiter.limit != settings.login_rate_limit_per_minute:
        _login_limiter = SlidingWindowRateLimiter(settings.login_rate_limit_per_minute, 60)
    return _login_limiter


def _set_session_cookie(response: Response, settings: Settings, token: str, max_age: int) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    responses={403: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Create a local account and start a session",
)
def register(
    data: RegisterRequest, response: Response, db: DbSession, settings: AppSettings
) -> UserOut:
    user = auth_service.register(db, settings, data)
    token, _ = auth_service.issue_token(settings, user)
    _set_session_cookie(response, settings, token, settings.access_token_ttl_minutes * 60)
    return UserOut.model_validate(user)


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    summary="Sign in with email and password",
)
def login(
    data: LoginRequest, request: Request, response: Response, db: DbSession, settings: AppSettings
) -> LoginResponse:
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{auth_service.normalize_email(data.email)}"
    if not get_login_limiter(settings).hit(key):
        raise RateLimitedError("Too many sign-in attempts. Wait a minute and try again.")
    user = auth_service.authenticate(db, settings, data)
    token, expires_at = auth_service.issue_token(settings, user)
    _set_session_cookie(response, settings, token, settings.access_token_ttl_minutes * 60)
    return LoginResponse(
        user=UserOut.model_validate(user), access_token=token, expires_at=expires_at
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End the session")
def logout(settings: AppSettings) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, path="/", samesite="lax", httponly=True)
    return response


@router.get(
    "/me",
    response_model=UserOut,
    responses={401: {"model": ErrorResponse}},
    summary="Current user",
)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
