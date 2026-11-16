"""Turn every error into an RFC 9457 "problem details" response.

Clients (the iOS app, later the web app) always get the same JSON shape:
    {"type": ..., "title": ..., "status": ..., "detail": ..., "errors": [...]}
with the content type application/problem+json.
"""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_CONTENT_TYPE = "application/problem+json"
PROBLEM_BASE_URI = "https://spendit.app/problems/"


class ProblemError(Exception):
    """Raise this from services to return a specific problem to the client."""

    def __init__(
        self,
        status: int,
        slug: str,
        detail: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        title: str | None = None,
    ) -> None:
        self.status = status
        self.slug = slug
        self.detail = detail
        self.errors = errors or []
        self.title = title or HTTPStatus(status).phrase
        super().__init__(detail or self.title)


def problem_response(
    status: int,
    slug: str,
    *,
    title: str | None = None,
    detail: str | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_BASE_URI + slug,
        "title": title or HTTPStatus(status).phrase,
        "status": status,
    }
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_CONTENT_TYPE)


async def _handle_problem(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)  # noqa: S101 - narrows the type for the checker
    return problem_response(
        exc.status, exc.slug, title=exc.title, detail=exc.detail, errors=exc.errors
    )


async def _handle_http(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    slug = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "-")
    detail = exc.detail if isinstance(exc.detail, str) else None
    return problem_response(exc.status_code, slug, detail=detail)


async def _handle_validation(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return problem_response(
        422,
        "validation-error",
        detail="The request body or parameters are invalid.",
        errors=errors,
    )


async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
    # Never leak internal details (stack traces, SQL) to clients.
    return problem_response(500, "internal-error", detail="Something went wrong on our side.")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _handle_problem)
    app.add_exception_handler(StarletteHTTPException, _handle_http)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(Exception, _handle_unexpected)
