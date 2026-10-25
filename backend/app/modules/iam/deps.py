"""Dependencias de autenticación y autorización en servidor (SEC-01).

Los permisos se leen de la base en cada request (no del JWT): suspender a un usuario,
quitarle un rol o cerrar su sesión surte efecto en la request siguiente.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.deps import SessionDep, SettingsDep
from app.core.config import Settings
from app.core.errors import ProblemError
from app.modules.iam.catalog import Perm
from app.modules.iam.cookies import ACCESS_COOKIE
from app.modules.iam.models import User, UserSession
from app.modules.iam.tokens import InvalidTokenError, decode_access_token
from app.modules.padron.models import Escribano

MFA_ENROLLMENT_TYPE = "urn:suite-notarial:auth:mfa-enrollment-required"


def get_request_context(request: Request) -> RequestContext:
    return RequestContext.from_request(request)


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]


# Permisos de autogestión que implican ejercer: solo con matrícula ACTIVA. Un escribano
# suspendido (o sin matrícula vinculada) conserva la consulta y puede adjuntar comprobantes
# para regularizar deudas, pero no presentar declaraciones juradas.
REQUIRES_ACTIVE_MATRICULA: frozenset[str] = frozenset({Perm.DDJJ_CREATE_OWN.value})


async def effective_permissions(session: AsyncSession, user: User) -> frozenset[str]:
    """Permisos de los roles, menos los que exigen matrícula activa si no la tiene."""
    permissions = user.permission_codes
    if not permissions & REQUIRES_ACTIVE_MATRICULA:
        return permissions
    estado = await session.scalar(
        select(Escribano.estado_matricula).where(Escribano.user_id == user.id)
    )
    if estado == "ACTIVO":
        return permissions
    return permissions - REQUIRES_ACTIVE_MATRICULA


@dataclass(frozen=True)
class Principal:
    user: User
    session: UserSession
    permissions: frozenset[str]

    @property
    def mfa_verified(self) -> bool:
        return self.session.mfa_verified


def _unauthenticated() -> ProblemError:
    return ProblemError(
        HTTPStatus.UNAUTHORIZED,
        "Necesitás iniciar sesión.",
        type_="urn:suite-notarial:auth:unauthenticated",
    )


async def get_principal(request: Request, session: SessionDep, settings: SettingsDep) -> Principal:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise _unauthenticated()
    try:
        claims = decode_access_token(settings, token)
    except InvalidTokenError as exc:
        raise _unauthenticated() from exc

    user_session = await session.get(UserSession, claims.session_id)
    if (
        user_session is None
        or user_session.user_id != claims.user_id
        or user_session.is_revoked
        or user_session.expires_at <= datetime.now(UTC)
    ):
        raise _unauthenticated()
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise _unauthenticated()
    return Principal(
        user=user,
        session=user_session,
        permissions=await effective_permissions(session, user),
    )


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def mfa_required_for(settings: Settings, user: User) -> bool:
    """El rol exige 2FA y la exigencia está activa (solo se apaga en desarrollo)."""
    return settings.MFA_ENFORCED and user.mfa_required


def _permission_checker(
    required: tuple[Perm, ...], *, any_of: bool
) -> Callable[..., Awaitable[Principal]]:
    async def checker(
        principal: PrincipalDep,
        session: SessionDep,
        settings: SettingsDep,
        ctx: RequestContextDep,
    ) -> Principal:
        user = principal.user
        if mfa_required_for(settings, user) and not principal.mfa_verified:
            raise ProblemError(
                HTTPStatus.FORBIDDEN,
                "Tu rol exige verificación en dos pasos. Activala para continuar.",
                type_=MFA_ENROLLMENT_TYPE,
            )
        missing = sorted(p.value for p in required if p.value not in principal.permissions)
        denied = len(missing) == len(required) if any_of else bool(missing)
        if denied:
            record_audit(
                session,
                ctx,
                AuditEvent.PERMISSION_DENIED,
                severity=Severity.WARNING,
                actor_user_id=user.id,
                details={"missing": missing, "path": ctx.path}
                | ({"any_of": True} if any_of else {}),
            )
            await session.commit()
            raise ProblemError(
                HTTPStatus.FORBIDDEN,
                "No tenés permiso para realizar esta acción.",
                type_="urn:suite-notarial:auth:forbidden",
                extra={"missing_permissions": missing},
            )
        return principal

    return checker


def require_permissions(*required: Perm) -> Callable[..., Awaitable[Principal]]:
    """Exige todos los permisos indicados. Los rechazos quedan auditados."""
    return _permission_checker(required, any_of=False)


def require_any_permission(*options: Perm) -> Callable[..., Awaitable[Principal]]:
    """Exige al menos uno de los permisos (p. ej. el propio o el de todo el padrón)."""
    return _permission_checker(options, any_of=True)
