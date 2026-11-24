"""HTTP middleware: request IDs, access logging, CSRF/Origin protection."""

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.errors import error_body
from app.core.logging import request_id_var

logger = logging.getLogger("pare.http")

CSRF_HEADER = "X-PARE-CSRF"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9\-_.]{1,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        if request.url.path not in {"/health", "/api/v1/health"}:
            logger.info(
                "%s %s %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        return response


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    """Protects cookie-authenticated, state-changing requests.

    * If an ``Origin`` header is present on an unsafe request it must be an allowed origin.
    * Unsafe requests that are not using an explicit ``Authorization`` header (i.e. browser
      requests relying on the session cookie) must carry ``X-PARE-CSRF: 1``. Browsers will
      not let a cross-origin page set this header without a CORS preflight, and CORS only
      allows the configured web origin.
    """

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self.allowed_origins = set(allowed_origins)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin not in self.allowed_origins:
                return JSONResponse(
                    status_code=403,
                    content=error_body("FORBIDDEN_ORIGIN", "Request origin is not allowed."),
                )
            uses_bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
            if not uses_bearer and request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse(
                    status_code=403,
                    content=error_body(
                        "CSRF_REQUIRED", f"Missing {CSRF_HEADER} header on state-changing request."
                    ),
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response
