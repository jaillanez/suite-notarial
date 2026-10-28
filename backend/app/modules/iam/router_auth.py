"""Endpoints de autenticación: /api/v1/auth."""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy import select

from app.common.cuit import format_cuit
from app.common.deps import SessionDep, SettingsDep
from app.core.config import Settings, get_settings
from app.core.errors import ProblemError
from app.core.mail import Mailer, SmtpMailer, send_safely
from app.modules.iam import service
from app.modules.iam.cookies import (
    MFA_COOKIE,
    REFRESH_COOKIE,
    clear_session_cookies,
    set_access_cookie,
    set_mfa_cookie,
    set_session_cookies,
)
from app.modules.iam.deps import (
    Principal,
    PrincipalDep,
    RequestContextDep,
    effective_permissions,
    mfa_required_for,
)
from app.modules.iam.mails import password_changed_mail, password_reset_mail
from app.modules.iam.models import User
from app.modules.iam.schemas import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    MfaCodeRequest,
    MfaDisableRequest,
    MfaLoginRequest,
    MfaSetupResponse,
    PasswordChange,
    PasswordResetConfirm,
    PasswordResetRequest,
    PerfilIn,
    PerfilOut,
    RecoveryCodesResponse,
    SessionUser,
)
from app.modules.iam.tokens import (
    InvalidTokenError,
    create_access_token,
    create_mfa_pending_token,
    decode_mfa_pending_token,
)
from app.modules.padron.models import Escribano

router = APIRouter(prefix="/auth", tags=["auth"])


def get_mailer(settings: Annotated[Settings, Depends(get_settings)]) -> Mailer:
    return SmtpMailer(settings)


MailerDep = Annotated[Mailer, Depends(get_mailer)]


def session_user(
    user: User, *, mfa_verified: bool, permissions: frozenset[str], mfa_required: bool
) -> SessionUser:
    return SessionUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        cuit=format_cuit(user.cuit),
        roles=user.role_codes,
        permissions=sorted(permissions),
        mfa_enabled=user.totp_enabled,
        mfa_required=mfa_required,
        mfa_verified=mfa_verified,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> LoginResponse:
    step = await service.authenticate_password(
        session, settings, ctx, body.identifier, body.password
    )
    if step.mfa_required:
        set_mfa_cookie(response, settings, create_mfa_pending_token(settings, user_id=step.user.id))
        return LoginResponse(status="mfa_required")
    issued = await service.issue_session(session, settings, ctx, step.user, mfa_verified=False)
    set_session_cookies(response, settings, issued.access_token, issued.refresh_token)
    permissions = await effective_permissions(session, step.user)
    return LoginResponse(
        status="authenticated",
        user=session_user(
            step.user,
            mfa_verified=False,
            permissions=permissions,
            mfa_required=mfa_required_for(settings, step.user),
        ),
    )


@router.post("/login/mfa", response_model=LoginResponse)
async def login_mfa(
    body: MfaLoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> LoginResponse:
    token = request.cookies.get(MFA_COOKIE)
    if not token:
        raise ProblemError(
            HTTPStatus.UNAUTHORIZED, "La verificación venció. Volvé a ingresar tu contraseña."
        )
    try:
        claims = decode_mfa_pending_token(settings, token)
    except InvalidTokenError as exc:
        raise ProblemError(
            HTTPStatus.UNAUTHORIZED, "La verificación venció. Volvé a ingresar tu contraseña."
        ) from exc
    user = await service.verify_mfa_login(session, settings, ctx, claims.user_id, body.code)
    issued = await service.issue_session(session, settings, ctx, user, mfa_verified=True)
    set_session_cookies(response, settings, issued.access_token, issued.refresh_token)
    permissions = await effective_permissions(session, user)
    return LoginResponse(
        status="authenticated",
        user=session_user(
            user,
            mfa_verified=True,
            permissions=permissions,
            mfa_required=mfa_required_for(settings, user),
        ),
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> LoginResponse:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise ProblemError(HTTPStatus.UNAUTHORIZED, "La sesión expiró. Volvé a ingresar.")
    try:
        issued = await service.refresh_session(session, settings, ctx, raw)
    except ProblemError:
        clear_session_cookies(response, settings)
        raise
    set_session_cookies(response, settings, issued.access_token, issued.refresh_token)
    user = await service.get_user(session, issued.session.user_id)
    if user is None:
        raise ProblemError(HTTPStatus.UNAUTHORIZED, "La sesión expiró. Volvé a ingresar.")
    return LoginResponse(
        status="authenticated",
        user=session_user(
            user,
            mfa_verified=issued.session.mfa_verified,
            permissions=await effective_permissions(session, user),
            mfa_required=mfa_required_for(settings, user),
        ),
    )


@router.post("/logout", status_code=HTTPStatus.NO_CONTENT)
async def logout(
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> Response:
    await service.logout(session, ctx, principal.user, principal.session)
    response = Response(status_code=HTTPStatus.NO_CONTENT)
    clear_session_cookies(response, settings)
    return response


@router.get("/me", response_model=SessionUser)
async def me(principal: PrincipalDep, settings: SettingsDep) -> SessionUser:
    return session_user(
        principal.user,
        mfa_verified=principal.mfa_verified,
        permissions=principal.permissions,
        mfa_required=mfa_required_for(settings, principal.user),
    )


@router.post("/password-reset/request", response_model=MessageResponse, status_code=202)
async def password_reset_request(
    body: PasswordResetRequest,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
    mailer: MailerDep,
) -> MessageResponse:
    result = await service.request_password_reset(session, settings, ctx, body.identifier)
    if result is not None:
        user, raw = result
        # El envío corre después de responder: la demora del SMTP no revela si la cuenta existe.
        background.add_task(send_safely, mailer, password_reset_mail(settings, user, raw))
    return MessageResponse(message=service.RESET_REQUEST_ACK)


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def password_reset_confirm(
    body: PasswordResetConfirm,
    response: Response,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
    mailer: MailerDep,
) -> MessageResponse:
    user = await service.confirm_password_reset(session, ctx, body.token, body.new_password)
    if user.password_changed_at is not None:
        background.add_task(
            send_safely, mailer, password_changed_mail(settings, user, user.password_changed_at)
        )
    clear_session_cookies(response, settings)
    return MessageResponse(message="La contraseña se actualizó. Ya podés ingresar con la nueva.")


@router.post("/password/change", response_model=MessageResponse)
async def password_change(
    body: PasswordChange,
    principal: PrincipalDep,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
    mailer: MailerDep,
) -> MessageResponse:
    user = principal.user
    await service.change_password(
        session,
        settings,
        ctx,
        user,
        principal.session,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    if user.password_changed_at is not None:
        background.add_task(
            send_safely,
            mailer,
            password_changed_mail(settings, user, user.password_changed_at, desde_la_cuenta=True),
        )
    return MessageResponse(
        message="La contraseña se cambió. Cerramos tus sesiones en otros dispositivos."
    )


async def _nombre_editable(session: SessionDep, user: User) -> bool:
    return await session.scalar(select(Escribano.id).where(Escribano.user_id == user.id)) is None


def _perfil(user: User, nombre_editable: bool) -> PerfilOut:
    return PerfilOut(
        email=user.email,
        full_name=user.full_name,
        cuit=format_cuit(user.cuit),
        phone_number=user.phone_number,
        nombre_editable=nombre_editable,
    )


@router.get("/perfil", response_model=PerfilOut)
async def ver_perfil(principal: PrincipalDep, session: SessionDep) -> PerfilOut:
    return _perfil(principal.user, await _nombre_editable(session, principal.user))


@router.patch("/perfil", response_model=PerfilOut)
async def editar_perfil(
    body: PerfilIn, principal: PrincipalDep, session: SessionDep, ctx: RequestContextDep
) -> PerfilOut:
    editable = await _nombre_editable(session, principal.user)
    user = await service.update_profile(
        session,
        ctx,
        principal.user,
        full_name=body.full_name,
        phone_number=body.phone_number,
        nombre_editable=editable,
    )
    return _perfil(user, editable)


@router.post("/mfa/setup", response_model=MfaSetupResponse)
async def mfa_setup(
    principal: PrincipalDep, session: SessionDep, settings: SettingsDep, ctx: RequestContextDep
) -> MfaSetupResponse:
    setup = await service.start_mfa_enrollment(session, settings, ctx, principal.user)
    return MfaSetupResponse(secret=setup.secret, otpauth_uri=setup.otpauth_uri, qr_svg=setup.qr_svg)


@router.post("/mfa/enable", response_model=RecoveryCodesResponse)
async def mfa_enable(
    body: MfaCodeRequest,
    response: Response,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> RecoveryCodesResponse:
    codes = await service.enable_mfa(
        session, settings, ctx, principal.user, principal.session, body.code
    )
    # El access token vigente no tenía la marca de 2FA: se reemplaza por uno que sí la tiene.
    _reissue_access(response, settings, principal)
    return RecoveryCodesResponse(recovery_codes=codes)


def _reissue_access(response: Response, settings: Settings, principal: Principal) -> None:
    access = create_access_token(
        settings,
        user_id=principal.user.id,
        session_id=principal.session.id,
        mfa=principal.session.mfa_verified,
    )
    set_access_cookie(response, settings, access)


@router.post("/mfa/disable", response_model=MessageResponse)
async def mfa_disable(
    body: MfaDisableRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> MessageResponse:
    await service.disable_mfa(
        session, settings, ctx, principal.user, password=body.password, code=body.code
    )
    return MessageResponse(message="La verificación en dos pasos quedó desactivada.")


@router.post("/mfa/recovery-codes", response_model=RecoveryCodesResponse)
async def mfa_recovery_codes(
    body: MfaCodeRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> RecoveryCodesResponse:
    codes = await service.regenerate_recovery_codes(
        session, settings, ctx, principal.user, body.code
    )
    return RecoveryCodesResponse(recovery_codes=codes)
