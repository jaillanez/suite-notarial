"""Middleware transversal: correlación de requests y cabeceras de endurecimiento."""

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from http import HTTPStatus

from fastapi import FastAPI, Request, Response

from app.core.config import Settings
from app.core.errors import problem_response

logger = logging.getLogger(__name__)

CORRELATION_HEADER = "X-Correlation-ID"
CLIENT_CORRELATION_HEADER = "X-Client-Correlation-ID"
# El ID autoritativo lo genera siempre el servidor. El del cliente se conserva aparte, solo si es
# acotado y seguro para logs, para que un cliente no pueda suplantar ni mezclar trazas ajenas.
_VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Los navegadores la ignoran sobre HTTP, por lo que es inocua en desarrollo.
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "XMLHttpRequest"


def _csrf_violation(request: Request, allowed_origins: frozenset[str]) -> str | None:
    """Defensa CSRF para la sesión en cookies.

    Un formulario de otro sitio no puede enviar cabeceras propias, y el navegador no deja que
    un script de otro origen las envíe sin pasar la verificación CORS. Además, si el navegador
    informa el `Origin`, debe ser uno de los orígenes de la Suite.
    """
    if request.method not in UNSAFE_METHODS or not request.url.path.startswith("/api/"):
        return None
    if request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        return f"Falta la cabecera {CSRF_HEADER}."
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in allowed_origins:
        return "Origen no permitido."
    return None


def _client_correlation_id(request: Request) -> str | None:
    incoming = request.headers.get(CORRELATION_HEADER, "")
    return incoming if _VALID_CORRELATION_ID.fullmatch(incoming) else None


def register_middleware(app: FastAPI, settings: Settings) -> None:
    allowed_origins = frozenset(
        [o.rstrip("/") for o in settings.CORS_ORIGINS] + [settings.public_web_base]
    )

    @app.middleware("http")
    async def correlation_and_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = str(uuid.uuid4())
        client_correlation_id = _client_correlation_id(request)
        request.state.correlation_id = correlation_id
        request.state.client_correlation_id = client_correlation_id
        response: Response
        try:
            violation = _csrf_violation(request, allowed_origins)
            if violation is not None:
                response = problem_response(
                    request,
                    HTTPStatus.FORBIDDEN,
                    violation,
                    type_="urn:suite-notarial:csrf",
                )
            else:
                response = await call_next(request)
        except Exception:
            # Se resuelve acá para que también los 500 lleven correlación y cabeceras.
            logger.exception(
                "Error no controlado",
                extra={
                    "path": request.url.path,
                    "correlation_id": correlation_id,
                    "client_correlation_id": client_correlation_id,
                },
            )
            response = problem_response(
                request, HTTPStatus.INTERNAL_SERVER_ERROR, "Error interno del servidor."
            )
        response.headers[CORRELATION_HEADER] = correlation_id
        if client_correlation_id:
            response.headers[CLIENT_CORRELATION_HEADER] = client_correlation_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response
