"""FastAPI application factory."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.api.v1.routes.system import health_router
from app.core.config import APP_VERSION, Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    CSRF_HEADER,
    CsrfOriginMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)

logger = logging.getLogger("pare")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="PARE API",
        version=APP_VERSION,
        description=(
            "Personal Autonomous Research Engine. Browser clients authenticate with the "
            f"`{settings.session_cookie_name}` cookie and must send `{CSRF_HEADER}: 1` on "
            "state-changing requests. Scripts may use `Authorization: Bearer <token>` "
            "from `/api/v1/auth/login` instead."
        ),
    )
    register_exception_handlers(app)

    # Starlette runs the last-added middleware first. Order (outer → inner):
    # RequestContext → CORS → TrustedHost → CSRF → SecurityHeaders → routes.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CsrfOriginMiddleware, allowed_origins=settings.cors_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", CSRF_HEADER, "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)

    # Root /health and /health/ready for container health checks (documented under /api/v1).
    app.include_router(health_router, include_in_schema=False)
    app.include_router(api_router)

    logger.info("PARE API %s started (environment=%s)", APP_VERSION, settings.environment)
    return app


app = create_app()
