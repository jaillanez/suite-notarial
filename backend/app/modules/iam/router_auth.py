"""Endpoints de autenticación: /api/v1/auth."""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response

from app.common.cuit import format_cuit
from app.common.deps import SessionDep, SettingsDep
from app.core.config import Settings, get_settings
from app.core.errors import ProblemError
from app.core.mail import Mailer, SmtpMailer, send_safely
from app.modules.iam import service
from app.modules.iam.cookies import (
    DEVICE_COOKIE,
    MFA_COOKIE,
    REFRESH_COOKIE,
    clear_session_cookies,
    set_access_cookie,
    set_device_cookie,
    set_mfa_cookie,
    set_session_cookies,
)
from app.modules.iam.deps import (
    Principal,
    PrincipalDep,
    RequestContextDep,
    effective_permissions,
    mfa_required_for,
    mfa_sugerido_for,
)
from app.modules.iam.mails import (
    email_change_mail,
    email_changed_mail,
    login_code_mail,
    password_changed_mail,
    password_reset_mail,
)
from app.modules.iam.models import User
from app.modules.iam.schemas import (
    CambioCorreoIn,
    ConfirmarCorreoIn,
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
    MfaPendingClaims,
    create_access_token,
    create_mfa_pending_token,
    decode_mfa_pending_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def get_mailer(settings: Annotated[Settings, Depends(get_settings)]) -> Mailer:
    return SmtpMailer(settings)


MailerDep = Annotated[Mailer, Depends(get_mailer)]


def session_user(
    user: User,
    *,
    mfa_verified: bool,
    permissions: frozenset[str],
    mfa_required: bool,
    mfa_sugerido: bool = False,
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
        mfa_sugerido=mfa_sugerido,
    )


def mask_email(email: str) -> str:
    """«h***@gmail.com»: alcanza para reconocer la dirección sin mostrarla entera."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def _email_code_challenge(
    response: Response,
    settings: Settings,
    background: BackgroundTasks,
    mailer: Mailer,
    user: User,
    code: service.LoginCode,
) -> LoginResponse:
    set_mfa_cookie(
        response, settings, create_mfa_pending_token(settings, user_id=user.id, code_id=code.id)
    )
    background.add_task(send_safely, mailer, login_code_mail(settings, user, code.raw))
    return LoginResponse(
        status="mfa_required", mfa_method="email", email_hint=mask_email(user.email)
    )


def _pending_claims(request: Request, settings: Settings) -> MfaPendingClaims:
    expired = ProblemError(
        HTTPStatus.UNAUTHORIZED, "La verificación venció. Volvé a ingresar tu contraseña."
    )
    token = request.cookies.get(MFA_COOKIE)
    if not token:
        raise expired
    try:
        return decode_mfa_pending_token(settings, token)
    except InvalidTokenError as exc:
        raise expired from exc


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
    mailer: MailerDep,
) -> LoginResponse:
    step = await service.authenticate_password(
        session,
        settings,
        ctx,
        body.identifier,
        body.password,
        device_token=request.cookies.get(DEVICE_COOKIE),
    )
    if step.mfa_required and step.email_code is not None:
        return _email_code_challenge(
            response, settings, background, mailer, step.user, step.email_code
        )
    if step.mfa_required:
        set_mfa_cookie(response, settings, create_mfa_pending_token(settings, user_id=step.user.id))
        return LoginResponse(status="mfa_required", mfa_method="totp")
    verified = step.trusted_device
    issued = await service.issue_session(session, settings, ctx, step.user, mfa_verified=verified)
    set_session_cookies(response, settings, issued.access_token, issued.refresh_token)
    permissions = await effective_permissions(session, step.user)
    return LoginResponse(
        status="authenticated",
        user=session_user(
            step.user,
            mfa_verified=verified,
            permissions=permissions,
            mfa_required=mfa_required_for(settings, step.user),
            mfa_sugerido=mfa_sugerido_for(settings, step.user),
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
    claims = _pending_claims(request, settings)
    user = await service.verify_mfa_login(
        session, settings, ctx, claims.user_id, body.code, claims.code_id
    )
    issued = await service.issue_session(session, settings, ctx, user, mfa_verified=True)
    set_session_cookies(response, settings, issued.access_token, issued.refresh_token)
    if body.recordar_equipo:
        token = await service.register_trusted_device(session, settings, ctx, user)
        set_device_cookie(response, settings, token)
    permissions = await effective_permissions(session, user)
    return LoginResponse(
        status="authenticated",
        user=session_user(
            user,
            mfa_verified=True,
            permissions=permissions,
            mfa_required=mfa_required_for(settings, user),
            mfa_sugerido=mfa_sugerido_for(settings, user),
        ),
    )


@router.post("/login/codigo", response_model=LoginResponse)
async def resend_login_code(
    request: Request,
    response: Response,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
    mailer: MailerDep,
) -> LoginResponse:
    """Reenvía el código por correo de un ingreso en curso (anula el anterior)."""
    claims = _pending_claims(request, settings)
    user, code = await service.resend_login_code(session, settings, ctx, claims.user_id)
    return _email_code_challenge(response, settings, background, mailer, user, code)


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
            mfa_sugerido=mfa_sugerido_for(settings, user),
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
        mfa_sugerido=mfa_sugerido_for(settings, principal.user),
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


def _perfil(user: User) -> PerfilOut:
    return PerfilOut(
        email=user.email,
        full_name=user.full_name,
        cuit=format_cuit(user.cuit),
        phone_number=user.phone_number,
        # El nombre lo administra la Caja, para todas las cuentas: no se edita desde la cuenta.
        nombre_editable=False,
    )


@router.get("/perfil", response_model=PerfilOut)
async def ver_perfil(principal: PrincipalDep, session: SessionDep) -> PerfilOut:
    return _perfil(principal.user)


@router.patch("/perfil", response_model=PerfilOut)
async def editar_perfil(
    body: PerfilIn, principal: PrincipalDep, session: SessionDep, ctx: RequestContextDep
) -> PerfilOut:
    user = await service.update_profile(
        session,
        ctx,
        principal.user,
        full_name=body.full_name,
        phone_number=body.phone_number,
    )
    return _perfil(user)


@router.post("/perfil/correo", response_model=MessageResponse, status_code=202)
async def pedir_cambio_correo(
    body: CambioCorreoIn,
    principal: PrincipalDep,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
    mailer: MailerDep,
) -> MessageResponse:
    """Cambio del correo de ingreso: manda un enlace a la dirección nueva para confirmarla."""
    user = principal.user
    raw = await service.request_email_change(
        session, settings, ctx, user, password=body.password, nuevo_email=str(body.nuevo_email)
    )
    nuevo = str(body.nuevo_email).strip().lower()
    if raw is not None:
        background.add_task(send_safely, mailer, email_change_mail(settings, user, nuevo, raw))
    return MessageResponse(
        message=f"Te mandamos un enlace a {nuevo}: abrilo para confirmar el cambio."
    )


@router.post("/perfil/correo/confirmar", response_model=MessageResponse)
async def confirmar_cambio_correo(
    body: ConfirmarCorreoIn,
    response: Response,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
    mailer: MailerDep,
) -> MessageResponse:
    """Confirma el cambio con el enlace del mail (no hace falta tener la sesión abierta)."""
    user, anterior = await service.confirm_email_change(session, ctx, body.token)
    background.add_task(send_safely, mailer, email_changed_mail(settings, user, anterior))
    # Las sesiones se cerraron: también la de este navegador.
    clear_session_cookies(response, settings)
    return MessageResponse(
        message=f"Listo: desde ahora ingresás con {user.email}. Volvé a ingresar con ese correo."
    )


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
