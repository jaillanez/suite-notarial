"""Administración de usuarios: alta, suspensión y roles. Toda acción queda auditada."""

import uuid
from datetime import UTC, datetime
from http import HTTPStatus

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.cuit import format_cuit
from app.common.pagination import PageParams
from app.core.config import Settings
from app.core.errors import ProblemError
from app.core.security import generate_token
from app.modules.iam import passwords
from app.modules.iam.models import Role, User, UserRole
from app.modules.iam.schemas import RoleOut, UserCreate, UserOut
from app.modules.iam.service import create_password_reset_token, revoke_all_user_sessions

ADMIN_ROLE = "ROLE_ADMIN"


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        cuit=format_cuit(user.cuit),
        phone_number=user.phone_number,
        roles=[r.code for r in user.roles],
        is_active=user.is_active,
        suspension_reason=user.suspension_reason,
        suspended_at=user.suspended_at,
        mfa_enabled=user.totp_enabled,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def role_out(role: Role) -> RoleOut:
    return RoleOut(
        code=role.code,
        name=role.name,
        description=role.description,
        mfa_required=role.mfa_required,
        permissions=[p.code for p in role.permissions],
    )


async def list_roles(session: AsyncSession) -> list[Role]:
    result = await session.execute(select(Role).where(Role.is_active.is_(True)).order_by(Role.code))
    return list(result.scalars())


def _filtered(query: str | None, is_active: bool | None) -> Select[User]:
    stmt = select(User)
    if query:
        like = f"%{query.strip().lower()}%"
        digits = "".join(ch for ch in query if ch.isdigit())
        conditions = [func.lower(User.full_name).like(like), User.email.like(like)]
        if digits:
            conditions.append(User.cuit.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conditions))
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    return stmt


async def list_users(
    session: AsyncSession, page: PageParams, *, query: str | None, is_active: bool | None
) -> tuple[list[User], int]:
    base = _filtered(query, is_active)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    result = await session.execute(
        base.order_by(User.full_name, User.id).offset(page.offset).limit(page.page_size)
    )
    return list(result.scalars()), total or 0


async def get_user_or_404(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El usuario no existe.")
    return user


async def _resolve_roles(session: AsyncSession, codes: list[str]) -> list[Role]:
    unique = sorted(set(codes))
    result = await session.execute(
        select(Role).where(Role.code.in_(unique), Role.is_active.is_(True))
    )
    roles = list(result.scalars())
    unknown = sorted(set(unique) - {r.code for r in roles})
    if unknown:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "Hay roles inexistentes o inactivos.",
            extra={"unknown_roles": unknown},
        )
    return roles


async def create_user(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    actor: User,
    data: UserCreate,
) -> tuple[User, str]:
    """Crea la cuenta sin contraseña utilizable y devuelve el token para que la defina."""
    roles = await _resolve_roles(session, data.roles)
    user = User(
        id=uuid.uuid4(),
        email=data.email,
        cuit=data.cuit,
        full_name=data.full_name,
        phone_number=data.phone_number,
        # Contraseña aleatoria descartada: la cuenta solo se activa con el enlace por correo.
        hashed_password=passwords.hash_password(generate_token(32)),
        created_by_user_id=actor.id,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ProblemError(
            HTTPStatus.CONFLICT, "Ya existe un usuario con ese correo o CUIT."
        ) from exc
    session.add_all(
        UserRole(user_id=user.id, role_id=role.id, assigned_by_user_id=actor.id) for role in roles
    )
    record_audit(
        session,
        ctx,
        AuditEvent.USER_CREATED,
        actor_user_id=actor.id,
        target_user_id=user.id,
        new_value={
            "email": user.email,
            "cuit": user.cuit,
            "full_name": user.full_name,
            "roles": sorted(r.code for r in roles),
        },
    )
    await session.commit()
    await session.refresh(user, attribute_names=["roles"])
    raw = await create_password_reset_token(session, settings, ctx, user)
    if raw is None:
        raise ProblemError(HTTPStatus.INTERNAL_SERVER_ERROR, "No se pudo emitir el enlace de alta.")
    return user, raw


async def set_user_status(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    user_id: uuid.UUID,
    *,
    is_active: bool,
    reason: str,
) -> User:
    user = await get_user_or_404(session, user_id)
    if user.id == actor.id:
        raise ProblemError(HTTPStatus.CONFLICT, "No podés cambiar el estado de tu propia cuenta.")
    if user.is_active == is_active:
        return user
    old = {"is_active": user.is_active, "suspension_reason": user.suspension_reason}
    user.is_active = is_active
    if is_active:
        user.suspension_reason = None
        user.suspended_at = None
        user.suspended_by_user_id = None
    else:
        user.suspension_reason = reason
        user.suspended_at = datetime.now(UTC)
        user.suspended_by_user_id = actor.id
        await revoke_all_user_sessions(session, user.id, "suspended")
    record_audit(
        session,
        ctx,
        AuditEvent.USER_STATUS_CHANGED,
        severity=Severity.WARNING if not is_active else Severity.INFO,
        actor_user_id=actor.id,
        target_user_id=user.id,
        old_value=old,
        new_value={"is_active": is_active, "suspension_reason": user.suspension_reason},
        details={"reason": reason},
    )
    await session.commit()
    return user


async def set_user_roles(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    user_id: uuid.UUID,
    codes: list[str],
) -> User:
    user = await get_user_or_404(session, user_id)
    roles = await _resolve_roles(session, codes)
    new_codes = sorted(r.code for r in roles)
    old_codes = sorted(r.code for r in user.roles)
    if user.id == actor.id and ADMIN_ROLE in old_codes and ADMIN_ROLE not in new_codes:
        raise ProblemError(
            HTTPStatus.CONFLICT, "No podés quitarte el rol de administrador a vos mismo."
        )
    if new_codes == old_codes:
        return user
    await session.execute(delete(UserRole).where(UserRole.user_id == user.id))
    session.add_all(
        UserRole(user_id=user.id, role_id=role.id, assigned_by_user_id=actor.id) for role in roles
    )
    record_audit(
        session,
        ctx,
        AuditEvent.USER_ROLES_CHANGED,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        target_user_id=user.id,
        old_value={"roles": old_codes},
        new_value={"roles": new_codes},
    )
    await session.commit()
    await session.refresh(user, attribute_names=["roles"])
    return user
