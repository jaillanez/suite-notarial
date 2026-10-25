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

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.deps import SessionDep, SettingsDep
from app.core.errors import ProblemError
from app.modules.iam.catalog import Perm
from app.modules.iam.cookies import ACCESS_COOKIE
from app.modules.iam.models import User, UserSession
from app.modules.iam.tokens import InvalidTokenError, decode_access_token

MFA_ENROLLMENT_TYPE = "urn:suite-notarial:auth:mfa-enrollment-required"


def get_request_context(request: Request) -> RequestContext:
    return RequestContext.from_request(request)


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]


@dataclass(frozen=True)
class Principal:
    user: User
    session: UserSession

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
    return Principal(user=user, session=user_session)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_permissions(*required: Perm) -> Callable[..., Awaitable[Principal]]:
    """Exige todos los permisos indicados. Los rechazos quedan auditados."""

    async def checker(
        principal: PrincipalDep, session: SessionDep, ctx: RequestContextDep
    ) -> Principal:
        user = principal.user
        if user.mfa_required and not principal.mfa_verified:
            raise ProblemError(
                HTTPStatus.FORBIDDEN,
                "Tu rol exige verificación en dos pasos. Activala para continuar.",
                type_=MFA_ENROLLMENT_TYPE,
            )
        missing = sorted(p.value for p in required if p.value not in user.permission_codes)
        if missing:
            record_audit(
                session,
                ctx,
                AuditEvent.PERMISSION_DENIED,
                severity=Severity.WARNING,
                actor_user_id=user.id,
                details={"missing": missing, "path": ctx.path},
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
