"""Errores de API en formato RFC 7807 (Problem Details, `application/problem+json`)."""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"

logger = logging.getLogger(__name__)


class ProblemError(Exception):
    """Excepción de dominio que se serializa como Problem Details."""

    def __init__(
        self,
        status: int,
        detail: str,
        *,
        title: str | None = None,
        type_: str = "about:blank",
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.title = title or HTTPStatus(status).phrase
        self.type = type_
        self.extra = extra or {}


def problem_response(
    request: Request,
    status: int,
    detail: str,
    *,
    title: str | None = None,
    type_: str = "about:blank",
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": type_,
        "title": title or HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
    }
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


async def _problem_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)  # noqa: S101
    return problem_response(
        request, exc.status, exc.detail, title=exc.title, type_=exc.type, extra=exc.extra
    )


async def _http_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    detail = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return problem_response(request, exc.status_code, detail, headers=getattr(exc, "headers", None))


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return problem_response(
        request,
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "La solicitud contiene datos inválidos.",
        extra={"errors": errors},
    )


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Error no controlado", extra={"path": request.url.path})
    return problem_response(
        request, HTTPStatus.INTERNAL_SERVER_ERROR, "Error interno del servidor."
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _problem_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
