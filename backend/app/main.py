"""Punto de entrada de la API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import register_middleware
from app.modules.cms.router import public_router as sitio_public_router
from app.modules.cms.router import router as cms_router
from app.modules.ddjj.router import public_router as boletas_public_router
from app.modules.ddjj.router import router as ddjj_router
from app.modules.health.router import router as health_router
from app.modules.ia.router import router as ia_router
from app.modules.iam.router_auth import router as auth_router
from app.modules.iam.router_users import router as users_router
from app.modules.migracion.router import router as migracion_router
from app.modules.padron.router import router as padron_router
from app.modules.padron.router_a_cargo import router as a_cargo_router
from app.modules.pagos.router import router as pagos_router
from app.modules.parametros.router import router as parametros_router
from app.modules.prestamos.router import router as prestamos_router
from app.modules.reportes.router import router as reportes_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    if not settings.MFA_ENFORCED:
        logging.getLogger(__name__).warning(
            "2FA obligatorio DESACTIVADO (MFA_ENFORCED=false): queda como recomendación."
        )

    app = FastAPI(
        title="Suite Notarial API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,  # cookies HttpOnly de sesión
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Requested-With", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID", "X-Client-Correlation-ID"],
    )
    register_middleware(app, settings)
    register_exception_handlers(app)
    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")
    app.include_router(padron_router, prefix="/api/v1")
    app.include_router(a_cargo_router, prefix="/api/v1")
    app.include_router(parametros_router, prefix="/api/v1")
    app.include_router(ddjj_router, prefix="/api/v1")
    app.include_router(boletas_public_router, prefix="/api/v1")
    app.include_router(pagos_router, prefix="/api/v1")
    app.include_router(reportes_router, prefix="/api/v1")
    app.include_router(cms_router, prefix="/api/v1")
    app.include_router(prestamos_router, prefix="/api/v1")
    app.include_router(ia_router, prefix="/api/v1")
    app.include_router(migracion_router, prefix="/api/v1")
    app.include_router(sitio_public_router, prefix="/api/v1")
    return app


app = create_app()
