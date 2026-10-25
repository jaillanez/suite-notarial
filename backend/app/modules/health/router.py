"""Healthcheck end-to-end: confirma que la API responde y la base acepta consultas."""

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.common.deps import SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["up", "down"]
    time_utc: datetime


@router.get("/health", response_model=HealthOut)
async def health(session: SessionDep) -> HealthOut:
    try:
        await session.execute(text("SELECT 1"))
        db_state: Literal["up", "down"] = "up"
    except (SQLAlchemyError, OSError):
        logger.warning("Healthcheck: base de datos no disponible", exc_info=True)
        db_state = "down"
    return HealthOut(
        status="ok" if db_state == "up" else "degraded",
        db=db_state,
        time_utc=datetime.now(UTC),
    )
