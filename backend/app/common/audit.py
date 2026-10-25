"""Auditoría de seguridad inmutable (regla AUD / SEC-03).

La tabla `audit_security_logs` está protegida por un trigger que rechaza UPDATE, DELETE y
TRUNCATE: una vez escrita, una fila no se modifica. La fila se agrega a la misma sesión que
la acción auditada, de modo que ambas se confirman o se revierten juntas.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from fastapi import Request
from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AuditEvent(StrEnum):
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGIN_LOCKED = "LOGIN_LOCKED"
    LOGIN_MFA_CHALLENGE = "LOGIN_MFA_CHALLENGE"
    LOGIN_MFA_FAILED = "LOGIN_MFA_FAILED"
    LOGIN_RECOVERY_CODE_USED = "LOGIN_RECOVERY_CODE_USED"
    LOGOUT = "LOGOUT"
    SESSION_REFRESHED = "SESSION_REFRESHED"
    SESSION_REUSE_DETECTED = "SESSION_REUSE_DETECTED"
    MFA_ENROLLMENT_STARTED = "MFA_ENROLLMENT_STARTED"
    MFA_ENABLED = "MFA_ENABLED"
    MFA_DISABLED = "MFA_DISABLED"
    MFA_RECOVERY_CODES_REGENERATED = "MFA_RECOVERY_CODES_REGENERATED"
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"
    PASSWORD_RESET_COMPLETED = "PASSWORD_RESET_COMPLETED"
    PASSWORD_RESET_REJECTED = "PASSWORD_RESET_REJECTED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    USER_CREATED = "USER_CREATED"
    USER_STATUS_CHANGED = "USER_STATUS_CHANGED"
    USER_ROLES_CHANGED = "USER_ROLES_CHANGED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PADRON_CIRCUNSCRIPCION_CREATED = "PADRON_CIRCUNSCRIPCION_CREATED"
    PADRON_CIRCUNSCRIPCION_UPDATED = "PADRON_CIRCUNSCRIPCION_UPDATED"
    PADRON_REGISTRO_CREATED = "PADRON_REGISTRO_CREATED"
    PADRON_REGISTRO_UPDATED = "PADRON_REGISTRO_UPDATED"
    PADRON_REGISTRO_CLOSED = "PADRON_REGISTRO_CLOSED"
    PADRON_ESCRIBANO_CREATED = "PADRON_ESCRIBANO_CREATED"
    PADRON_ESCRIBANO_UPDATED = "PADRON_ESCRIBANO_UPDATED"
    PADRON_ESTADO_CHANGED = "PADRON_ESTADO_CHANGED"
    PADRON_CARGO_ASSIGNED = "PADRON_CARGO_ASSIGNED"
    PADRON_CARGO_CLOSED = "PADRON_CARGO_CLOSED"
    PADRON_CUENTA_CREATED = "PADRON_CUENTA_CREATED"
    PARAMETRO_CONCEPTO_CREATED = "PARAMETRO_CONCEPTO_CREATED"
    PARAMETRO_CONCEPTO_UPDATED = "PARAMETRO_CONCEPTO_UPDATED"
    PARAMETRO_VIGENCIA_PROPUESTA = "PARAMETRO_VIGENCIA_PROPUESTA"
    PARAMETRO_VIGENCIA_APROBADA = "PARAMETRO_VIGENCIA_APROBADA"
    PARAMETRO_VIGENCIA_RECHAZADA = "PARAMETRO_VIGENCIA_RECHAZADA"
    PARAMETRO_VIGENCIA_CERRADA = "PARAMETRO_VIGENCIA_CERRADA"
    DDJJ_ABIERTA = "DDJJ_ABIERTA"
    DDJJ_ACTO_AGREGADO = "DDJJ_ACTO_AGREGADO"
    DDJJ_ACTO_BAJA = "DDJJ_ACTO_BAJA"
    DDJJ_PRESENTADA = "DDJJ_PRESENTADA"
    DDJJ_RECTIFICATIVA_ABIERTA = "DDJJ_RECTIFICATIVA_ABIERTA"
    BOLETA_EMITIDA = "BOLETA_EMITIDA"
    BOLETA_ANULADA = "BOLETA_ANULADA"
    VENCIMIENTO_FIJADO = "VENCIMIENTO_FIJADO"


class AuditSecurityLog(UUIDMixin, Base):
    __tablename__ = "audit_security_logs"

    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default=Severity.INFO)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True, index=True
    )
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True, index=True
    )
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


@dataclass(frozen=True)
class RequestContext:
    """Datos de origen de una request que se registran en cada evento auditado."""

    ip_address: str | None
    user_agent: str | None
    correlation_id: str | None
    path: str | None = None

    @classmethod
    def from_request(cls, request: Request) -> "RequestContext":
        user_agent = request.headers.get("user-agent")
        return cls(
            ip_address=request.client.host if request.client else None,
            user_agent=user_agent[:500] if user_agent else None,
            correlation_id=getattr(request.state, "correlation_id", None),
            path=f"{request.method} {request.url.path}",
        )


def record_audit(
    session: AsyncSession,
    ctx: RequestContext,
    event: AuditEvent,
    *,
    severity: Severity = Severity.INFO,
    actor_user_id: uuid.UUID | None = None,
    target_user_id: uuid.UUID | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> AuditSecurityLog:
    entry = AuditSecurityLog(
        event_type=event.value,
        severity=severity.value,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
        correlation_id=ctx.correlation_id,
        old_value=old_value,
        new_value=new_value,
        details=details,
    )
    session.add(entry)
    return entry
