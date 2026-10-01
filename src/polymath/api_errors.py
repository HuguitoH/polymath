"""RFC 9457 Problem Details, plus request correlation."""

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from polymath.observability.logs import correlation_id

logger = logging.getLogger(__name__)

PROBLEM_BASE = "https://stem-buddy.hugohhm.dev/problems"

# Human-readable summaries per status. RFC 9457 expects a stable, short
# description of the problem type, not an exception class name.
_TITLES: dict[int, tuple[str, str]] = {
    400: ("Malformed request", "bad-request"),
    401: ("Authentication required", "unauthorized"),
    404: ("Resource not found", "not-found"),
    409: ("Conflicting state", "conflict"),
    422: ("Request validation failed", "validation-error"),
    503: ("Dependency unavailable", "unavailable"),
}


class Problem(BaseModel):
    """RFC 9457 problem details."""

    type: str
    title: str
    status: int
    detail: str
    instance: str


def _problem(request: Request, status: int, slug: str, title: str, detail: str) -> JSONResponse:
    body = Problem(
        type=f"{PROBLEM_BASE}/{slug}",
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
    )
    return JSONResponse(
        status_code=status,
        content=body.model_dump(),
        media_type="application/problem+json",
        headers={"X-Correlation-Id": correlation_id.get() or ""},
    )


def install(app: FastAPI) -> None:
    """Attach correlation middleware and problem-details handlers."""

    @app.middleware("http")
    async def correlate(
        request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ) -> JSONResponse:
        token = correlation_id.set(request.headers.get("X-Correlation-Id") or str(uuid.uuid4()))
        try:
            response = await call_next(request)
            response.headers["X-Correlation-Id"] = correlation_id.get() or ""
            return response
        finally:
            correlation_id.reset(token)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title, slug = _TITLES.get(exc.status_code, ("Request failed", "http-error"))
        return _problem(request, exc.status_code, slug, title, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(
            request,
            422,
            "validation-error",
            "Request validation failed",
            "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()),
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the cause; never leak internals to the client.
        logger.exception("unhandled error", extra={"path": request.url.path})
        return _problem(
            request,
            500,
            "internal-error",
            "Internal server error",
            "An unexpected error occurred. The correlation id identifies this request.",
        )
