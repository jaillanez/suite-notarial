"""Middleware transversal: correlación de requests y cabeceras de endurecimiento."""

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from http import HTTPStatus

from fastapi import FastAPI, Request, Response

from app.core.errors import problem_response

logger = logging.getLogger(__name__)

CORRELATION_HEADER = "X-Correlation-ID"
# Solo se acepta un ID entrante acotado y seguro para logs; si no, se genera uno nuevo.
_VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Los navegadores la ignoran sobre HTTP, por lo que es inocua en desarrollo.
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


def _correlation_id(request: Request) -> str:
    incoming = request.headers.get(CORRELATION_HEADER, "")
    return incoming if _VALID_CORRELATION_ID.fullmatch(incoming) else str(uuid.uuid4())


def register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_and_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = _correlation_id(request)
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        except Exception:
            # Se resuelve acá para que también los 500 lleven correlación y cabeceras.
            logger.exception(
                "Error no controlado",
                extra={"path": request.url.path, "correlation_id": correlation_id},
            )
            response = problem_response(
                request, HTTPStatus.INTERNAL_SERVER_ERROR, "Error interno del servidor."
            )
        response.headers[CORRELATION_HEADER] = correlation_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response
