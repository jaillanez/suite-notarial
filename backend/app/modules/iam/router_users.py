"""Administración de usuarios y lectura de auditoría: /api/v1/users, /roles, /audit."""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.common.audit import AuditSecurityLog
from app.common.deps import SessionDep, SettingsDep
from app.common.pagination import Page, PageParamsDep
from app.core.mail import send_safely
from app.modules.iam import users_service
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal, RequestContextDep, require_permissions
from app.modules.iam.mails import account_created_mail
from app.modules.iam.models import User
from app.modules.iam.router_auth import MailerDep
from app.modules.iam.schemas import (
    AuditLogOut,
    RoleOut,
    UserCreate,
    UserOut,
    UserRolesUpdate,
    UserStatusUpdate,
)

router = APIRouter(tags=["users"])

CanReadUsers = Annotated[Principal, Depends(require_permissions(Perm.USERS_READ))]
CanWriteUsers = Annotated[Principal, Depends(require_permissions(Perm.USERS_WRITE))]
CanSuspendUsers = Annotated[Principal, Depends(require_permissions(Perm.USERS_SUSPEND))]
CanManageRoles = Annotated[Principal, Depends(require_permissions(Perm.ROLES_MANAGE))]
CanReadAudit = Annotated[Principal, Depends(require_permissions(Perm.AUDIT_READ))]


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(_: CanReadUsers, session: SessionDep) -> list[RoleOut]:
    return [users_service.role_out(r) for r in await users_service.list_roles(session)]


@router.get("/users", response_model=Page[UserOut])
async def list_users(
    _: CanReadUsers,
    session: SessionDep,
    page: PageParamsDep,
    q: Annotated[str | None, Query(max_length=100, description="Nombre, email o CUIT")] = None,
    is_active: bool | None = None,
) -> Page[UserOut]:
    users, total = await users_service.list_users(session, page, query=q, is_active=is_active)
    return Page(
        items=[users_service.user_out(u) for u in users],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, _: CanReadUsers, session: SessionDep) -> UserOut:
    return users_service.user_out(await users_service.get_user_or_404(session, user_id))


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    principal: CanWriteUsers,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
    mailer: MailerDep,
) -> UserOut:
    user, raw = await users_service.create_user(session, settings, ctx, principal.user, body)
    background.add_task(send_safely, mailer, account_created_mail(settings, user, raw))
    return users_service.user_out(user)


@router.patch("/users/{user_id}/status", response_model=UserOut)
async def set_user_status(
    user_id: uuid.UUID,
    body: UserStatusUpdate,
    principal: CanSuspendUsers,
    session: SessionDep,
    ctx: RequestContextDep,
) -> UserOut:
    user = await users_service.set_user_status(
        session, ctx, principal.user, user_id, is_active=body.is_active, reason=body.reason
    )
    return users_service.user_out(user)


@router.put("/users/{user_id}/roles", response_model=UserOut)
async def set_user_roles(
    user_id: uuid.UUID,
    body: UserRolesUpdate,
    principal: CanManageRoles,
    session: SessionDep,
    ctx: RequestContextDep,
) -> UserOut:
    user = await users_service.set_user_roles(session, ctx, principal.user, user_id, body.roles)
    return users_service.user_out(user)


@router.get("/audit/security-logs", response_model=Page[AuditLogOut])
async def list_audit_logs(
    _: CanReadAudit,
    session: SessionDep,
    page: PageParamsDep,
    event_type: Annotated[str | None, Query(max_length=100)] = None,
    user_id: uuid.UUID | None = None,
) -> Page[AuditLogOut]:
    stmt = select(AuditSecurityLog)
    if event_type:
        stmt = stmt.where(AuditSecurityLog.event_type == event_type)
    if user_id:
        stmt = stmt.where(
            (AuditSecurityLog.actor_user_id == user_id)
            | (AuditSecurityLog.target_user_id == user_id)
        )
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    actor = aliased(User)
    target = aliased(User)
    result = await session.execute(
        stmt.add_columns(actor.email, target.email)
        .outerjoin(actor, actor.id == AuditSecurityLog.actor_user_id)
        .outerjoin(target, target.id == AuditSecurityLog.target_user_id)
        .order_by(AuditSecurityLog.event_timestamp.desc(), AuditSecurityLog.id)
        .offset(page.offset)
        .limit(page.page_size)
    )
    items = []
    for row, actor_email, target_email in result.all():
        item = AuditLogOut.model_validate(row)
        item.actor_email = actor_email
        item.target_email = target_email
        items.append(item)
    return Page(
        items=items,
        total=total or 0,
        page=page.page,
        page_size=page.page_size,
    )
