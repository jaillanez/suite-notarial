"""Lógica de autenticación: login, 2FA, sesiones rotativas, recuperación de contraseña.

Cada función confirma su propia unidad de trabajo: la acción y su fila de auditoría se
escriben en la misma transacción. Los errores de credenciales son siempre genéricos para
no revelar si una cuenta existe, está suspendida o bloqueada (anti-enumeración).
"""

import contextlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.cuit import InvalidCuitError, normalize_cuit
from app.core.config import Settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.errors import ProblemError
from app.core.security import generate_token, sha256_hex
from app.modules.iam import passwords, totp
from app.modules.iam.models import PasswordResetToken, RecoveryCode, User, UserSession
from app.modules.iam.tokens import create_access_token

INVALID_CREDENTIALS = (
    "Las credenciales no son válidas. Después de varios intentos fallidos la cuenta se "
    "bloquea temporalmente."
)
INVALID_MFA = "El código de verificación no es válido o ya fue utilizado."
INVALID_RESET_TOKEN = (
    "El enlace de recuperación no es válido, venció o ya fue utilizado. Solicitá uno nuevo."
)
RESET_REQUEST_ACK = (
    "Si la cuenta indicada está registrada y activa, vas a recibir un correo con los pasos "
    "para restablecer la contraseña."
)
MAX_RESET_REQUESTS_PER_HOUR = 3
# Ventana en la que un refresh ya rotado se trata como pedido concurrente (otra pestaña),
# no como robo del token.
REFRESH_CONCURRENCY_GRACE = timedelta(seconds=10)


def _now() -> datetime:
    return datetime.now(UTC)


def _credentials_error(detail: str = INVALID_CREDENTIALS) -> ProblemError:
    return ProblemError(HTTPStatus.UNAUTHORIZED, detail, type_="urn:suite-notarial:auth:invalid")


def _totp_aad(user: User) -> bytes:
    # Ata el secreto cifrado al usuario: copiarlo a otra fila no sirve para descifrarlo.
    return f"totp:{user.id}".encode()


# --------------------------------------------------------------------------- búsqueda


def _identifier_fingerprint(identifier: str) -> dict[str, str]:
    """Huella del identificador para la auditoría, nunca el texto.

    Quien tipea la contraseña en el campo de usuario no debe dejarla escrita en la auditoría;
    el hash permite correlacionar intentos repetidos sin conservar el valor.
    """
    normalized = identifier.strip().lower()
    try:
        normalize_cuit(normalized)
        kind = "cuit"
    except InvalidCuitError:
        kind = "email" if "@" in normalized else "other"
    return {"identifier_kind": kind, "identifier_sha256": sha256_hex(normalized)}


async def find_user_by_identifier(session: AsyncSession, identifier: str) -> User | None:
    identifier = identifier.strip()
    conditions = [User.email == identifier.lower()]
    with contextlib.suppress(InvalidCuitError):
        conditions.append(User.cuit == normalize_cuit(identifier))
    result = await session.execute(select(User).where(or_(*conditions)))
    return result.scalars().first()


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


# --------------------------------------------------------------------------- login


@dataclass(frozen=True)
class PasswordStep:
    user: User
    mfa_required: bool


async def _register_failure(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    user: User,
    event: AuditEvent,
) -> None:
    # Se relee la fila bloqueada antes de sumar: intentos en paralelo se serializan y ninguno
    # pierde su incremento (si no, el bloqueo se podía esquivar con pedidos concurrentes).
    await session.refresh(
        user, attribute_names=["failed_login_attempts", "locked_until"], with_for_update=True
    )
    user.failed_login_attempts += 1
    details: dict[str, object] = {"failed_attempts": user.failed_login_attempts}
    if user.failed_login_attempts >= settings.LOGIN_MAX_ATTEMPTS:
        user.locked_until = _now() + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
        user.failed_login_attempts = 0
        details["locked_until"] = user.locked_until.isoformat()
        record_audit(
            session,
            ctx,
            AuditEvent.LOGIN_LOCKED,
            severity=Severity.WARNING,
            target_user_id=user.id,
            details=details,
        )
    else:
        record_audit(
            session,
            ctx,
            event,
            severity=Severity.WARNING,
            target_user_id=user.id,
            details=details,
        )
    await session.commit()


def _is_locked(user: User) -> bool:
    return user.locked_until is not None and user.locked_until > _now()


async def authenticate_password(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    identifier: str,
    password: str,
) -> PasswordStep:
    user = await find_user_by_identifier(session, identifier)
    if user is None:
        await passwords.burn_verification_time_async(password)
        record_audit(
            session,
            ctx,
            AuditEvent.LOGIN_FAILED,
            severity=Severity.WARNING,
            details={"reason": "unknown_identifier", **_identifier_fingerprint(identifier)},
        )
        await session.commit()
        raise _credentials_error()

    if _is_locked(user):
        await passwords.burn_verification_time_async(password)
        record_audit(
            session,
            ctx,
            AuditEvent.LOGIN_FAILED,
            severity=Severity.WARNING,
            target_user_id=user.id,
            details={"reason": "locked"},
        )
        await session.commit()
        raise _credentials_error()

    if not await passwords.verify_password_async(user.hashed_password, password):
        await _register_failure(session, settings, ctx, user, AuditEvent.LOGIN_FAILED)
        raise _credentials_error()

    if not user.is_active:
        record_audit(
            session,
            ctx,
            AuditEvent.LOGIN_FAILED,
            severity=Severity.WARNING,
            target_user_id=user.id,
            details={"reason": "suspended"},
        )
        await session.commit()
        raise _credentials_error()

    if passwords.needs_rehash(user.hashed_password):
        user.hashed_password = await passwords.hash_password_async(password)

    if user.totp_enabled:
        record_audit(session, ctx, AuditEvent.LOGIN_MFA_CHALLENGE, target_user_id=user.id)
        await session.commit()
        return PasswordStep(user=user, mfa_required=True)
    return PasswordStep(user=user, mfa_required=False)


def _decrypt_totp_secret(settings: Settings, user: User) -> str:
    if user.totp_secret_encrypted is None:
        raise ProblemError(HTTPStatus.CONFLICT, "La verificación en dos pasos no está configurada.")
    return decrypt_secret(
        user.totp_secret_encrypted, settings.data_encryption_key, associated_data=_totp_aad(user)
    )


def _recovery_hash(settings: Settings, user: User, code: str) -> str:
    return totp.hash_recovery_code(
        code, key=totp.recovery_code_key(settings.data_encryption_key), user_id=str(user.id)
    )


async def _consume_recovery_code(
    session: AsyncSession, settings: Settings, user: User, code: str
) -> bool:
    if not totp.looks_like_recovery_code(code):
        return False
    # Una sola búsqueda indexada: el costo no depende de cuántos códigos queden.
    result = await session.execute(
        select(RecoveryCode)
        .where(
            RecoveryCode.user_id == user.id,
            RecoveryCode.code_hash == _recovery_hash(settings, user, code),
            RecoveryCode.used_at.is_(None),
        )
        .with_for_update()
    )
    record = result.scalars().first()
    if record is None:
        return False
    record.used_at = _now()
    return True


async def verify_mfa_login(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    user_id: uuid.UUID,
    code: str,
) -> User:
    user = await get_user(session, user_id)
    if user is None or not user.is_active or not user.totp_enabled or _is_locked(user):
        raise _credentials_error(INVALID_MFA)

    secret = _decrypt_totp_secret(settings, user)
    step = totp.verify_code(secret, code, last_used_step=user.totp_last_used_step)
    if step is not None:
        user.totp_last_used_step = step
        return user

    if await _consume_recovery_code(session, settings, user, code):
        remaining = await session.scalar(
            select(func.count())
            .select_from(RecoveryCode)
            .where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
        )
        record_audit(
            session,
            ctx,
            AuditEvent.LOGIN_RECOVERY_CODE_USED,
            severity=Severity.WARNING,
            actor_user_id=user.id,
            target_user_id=user.id,
            details={"remaining_codes": remaining},
        )
        return user

    await _register_failure(session, settings, ctx, user, AuditEvent.LOGIN_MFA_FAILED)
    raise _credentials_error(INVALID_MFA)


# --------------------------------------------------------------------------- sesiones


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_token: str
    session: UserSession


def _new_session(
    settings: Settings,
    ctx: RequestContext,
    user: User,
    *,
    family_id: uuid.UUID,
    mfa_verified: bool,
) -> tuple[UserSession, str]:
    raw_refresh = generate_token(48)
    record = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        refresh_token_hash=sha256_hex(raw_refresh),
        session_family_id=family_id,
        mfa_verified=mfa_verified,
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
        expires_at=_now() + timedelta(days=settings.JWT_REFRESH_TTL_DAYS),
    )
    return record, raw_refresh


async def issue_session(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    user: User,
    *,
    mfa_verified: bool,
) -> IssuedSession:
    record, raw_refresh = _new_session(
        settings, ctx, user, family_id=uuid.uuid4(), mfa_verified=mfa_verified
    )
    session.add(record)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = _now()
    user.last_login_ip = ctx.ip_address
    record_audit(
        session,
        ctx,
        AuditEvent.LOGIN_SUCCESS,
        actor_user_id=user.id,
        target_user_id=user.id,
        details={"roles": user.role_codes, "mfa_verified": mfa_verified},
    )
    await session.commit()
    access = create_access_token(settings, user_id=user.id, session_id=record.id, mfa=mfa_verified)
    return IssuedSession(access_token=access, refresh_token=raw_refresh, session=record)


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, reason: str) -> None:
    await session.execute(
        update(UserSession)
        .where(UserSession.session_family_id == family_id, UserSession.is_revoked.is_(False))
        .values(is_revoked=True, revoked_at=_now(), revoked_reason=reason)
    )


async def revoke_all_user_sessions(session: AsyncSession, user_id: uuid.UUID, reason: str) -> None:
    await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.is_revoked.is_(False))
        .values(is_revoked=True, revoked_at=_now(), revoked_reason=reason)
    )


async def refresh_session(
    session: AsyncSession, settings: Settings, ctx: RequestContext, raw_refresh: str
) -> IssuedSession:
    expired = ProblemError(HTTPStatus.UNAUTHORIZED, "La sesión expiró. Volvé a ingresar.")
    # FOR UPDATE: dos refresh simultáneos del mismo token se serializan; el segundo ve la
    # fila ya rotada y no puede emitir una segunda sesión válida.
    result = await session.execute(
        select(UserSession)
        .where(UserSession.refresh_token_hash == sha256_hex(raw_refresh))
        .with_for_update()
    )
    current = result.scalars().first()
    if current is None:
        raise expired

    now = _now()
    if current.rotated_at is not None or current.is_revoked:
        concurrent = current.rotated_at is not None and now - current.rotated_at < (
            REFRESH_CONCURRENCY_GRACE
        )
        if not concurrent:
            # Un refresh ya usado volvió a presentarse: el token pudo haber sido robado.
            await _revoke_family(session, current.session_family_id, "reuse_detected")
            record_audit(
                session,
                ctx,
                AuditEvent.SESSION_REUSE_DETECTED,
                severity=Severity.CRITICAL,
                target_user_id=current.user_id,
                details={"session_family_id": str(current.session_family_id)},
            )
            await session.commit()
        raise expired

    user = await get_user(session, current.user_id)
    if current.expires_at <= now or user is None or not user.is_active:
        current.is_revoked = True
        current.revoked_at = now
        current.revoked_reason = "expired" if current.expires_at <= now else "user_inactive"
        await session.commit()
        raise expired

    current.rotated_at = now
    current.is_revoked = True
    current.revoked_at = now
    current.revoked_reason = "rotated"
    record, raw = _new_session(
        settings,
        ctx,
        user,
        family_id=current.session_family_id,
        mfa_verified=current.mfa_verified,
    )
    session.add(record)
    record_audit(
        session,
        ctx,
        AuditEvent.SESSION_REFRESHED,
        actor_user_id=user.id,
        target_user_id=user.id,
        details={"session_family_id": str(current.session_family_id)},
    )
    await session.commit()
    access = create_access_token(
        settings, user_id=user.id, session_id=record.id, mfa=record.mfa_verified
    )
    return IssuedSession(access_token=access, refresh_token=raw, session=record)


async def logout(
    session: AsyncSession, ctx: RequestContext, user: User, current: UserSession
) -> None:
    await _revoke_family(session, current.session_family_id, "logout")
    record_audit(
        session,
        ctx,
        AuditEvent.LOGOUT,
        actor_user_id=user.id,
        target_user_id=user.id,
        details={"session_family_id": str(current.session_family_id)},
    )
    await session.commit()


# --------------------------------------------------------------------------- 2FA


@dataclass(frozen=True)
class MfaSetup:
    secret: str
    otpauth_uri: str
    qr_svg: str


async def start_mfa_enrollment(
    session: AsyncSession, settings: Settings, ctx: RequestContext, user: User
) -> MfaSetup:
    if user.totp_enabled:
        raise ProblemError(HTTPStatus.CONFLICT, "La verificación en dos pasos ya está activa.")
    secret = totp.generate_secret()
    user.totp_secret_encrypted = encrypt_secret(
        secret, settings.data_encryption_key, associated_data=_totp_aad(user)
    )
    user.totp_last_used_step = None
    record_audit(
        session,
        ctx,
        AuditEvent.MFA_ENROLLMENT_STARTED,
        actor_user_id=user.id,
        target_user_id=user.id,
    )
    await session.commit()
    uri = totp.provisioning_uri(secret, account=user.email, issuer=settings.TOTP_ISSUER)
    return MfaSetup(secret=secret, otpauth_uri=uri, qr_svg=totp.qr_svg(uri))


async def _replace_recovery_codes(
    session: AsyncSession, settings: Settings, user: User
) -> list[str]:
    existing = await session.execute(select(RecoveryCode).where(RecoveryCode.user_id == user.id))
    for code in existing.scalars():
        await session.delete(code)
    await session.flush()
    codes = totp.generate_recovery_codes()
    session.add_all(
        RecoveryCode(user_id=user.id, code_hash=_recovery_hash(settings, user, c)) for c in codes
    )
    return codes


async def _require_valid_totp(
    session: AsyncSession, settings: Settings, ctx: RequestContext, user: User, code: str
) -> None:
    """Valida un código TOTP en una acción con sesión abierta.

    Los fallos cuentan para el mismo bloqueo que el ingreso: una sesión robada no sirve para
    probar códigos por fuerza bruta. Al bloquearse la cuenta se cierran todas sus sesiones.
    """
    if _is_locked(user):
        raise ProblemError(HTTPStatus.FORBIDDEN, "La cuenta está bloqueada temporalmente.")
    secret = _decrypt_totp_secret(settings, user)
    step = totp.verify_code(secret, code, last_used_step=user.totp_last_used_step)
    if step is None:
        await _register_failure(session, settings, ctx, user, AuditEvent.LOGIN_MFA_FAILED)
        if _is_locked(user):
            await revoke_all_user_sessions(session, user.id, "mfa_lockout")
            await session.commit()
        raise ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, INVALID_MFA)
    user.totp_last_used_step = step


async def enable_mfa(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    user: User,
    current: UserSession,
    code: str,
) -> list[str]:
    if user.totp_enabled:
        raise ProblemError(HTTPStatus.CONFLICT, "La verificación en dos pasos ya está activa.")
    await _require_valid_totp(session, settings, ctx, user, code)
    user.totp_enabled = True
    codes = await _replace_recovery_codes(session, settings, user)
    # Quien acaba de probar la posesión del segundo factor queda verificado en esta sesión.
    current.mfa_verified = True
    record_audit(
        session,
        ctx,
        AuditEvent.MFA_ENABLED,
        actor_user_id=user.id,
        target_user_id=user.id,
        old_value={"totp_enabled": False},
        new_value={"totp_enabled": True},
    )
    await session.commit()
    return codes


async def disable_mfa(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    user: User,
    *,
    password: str,
    code: str,
) -> None:
    if not user.totp_enabled:
        raise ProblemError(HTTPStatus.CONFLICT, "La verificación en dos pasos no está activa.")
    if settings.MFA_ENFORCED and user.mfa_required:
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "Tu rol exige verificación en dos pasos: no se puede desactivar.",
        )
    if not await passwords.verify_password_async(user.hashed_password, password):
        await _register_failure(session, settings, ctx, user, AuditEvent.LOGIN_FAILED)
        raise ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, "La contraseña no es correcta.")
    await _require_valid_totp(session, settings, ctx, user, code)
    user.totp_enabled = False
    user.totp_secret_encrypted = None
    user.totp_last_used_step = None
    existing = await session.execute(select(RecoveryCode).where(RecoveryCode.user_id == user.id))
    for record in existing.scalars():
        await session.delete(record)
    record_audit(
        session,
        ctx,
        AuditEvent.MFA_DISABLED,
        severity=Severity.WARNING,
        actor_user_id=user.id,
        target_user_id=user.id,
        old_value={"totp_enabled": True},
        new_value={"totp_enabled": False},
    )
    await session.commit()


async def regenerate_recovery_codes(
    session: AsyncSession, settings: Settings, ctx: RequestContext, user: User, code: str
) -> list[str]:
    if not user.totp_enabled:
        raise ProblemError(HTTPStatus.CONFLICT, "La verificación en dos pasos no está activa.")
    await _require_valid_totp(session, settings, ctx, user, code)
    codes = await _replace_recovery_codes(session, settings, user)
    record_audit(
        session,
        ctx,
        AuditEvent.MFA_RECOVERY_CODES_REGENERATED,
        actor_user_id=user.id,
        target_user_id=user.id,
    )
    await session.commit()
    return codes


# --------------------------------------------------------------------------- contraseñas


def reset_link(settings: Settings, raw_token: str) -> str:
    """Enlace de recuperación siempre bajo `PUBLIC_WEB_URL` (SEC-04).

    El token va en el fragmento (`#`), que el navegador no envía al servidor ni en `Referer`.
    """
    return f"{settings.public_web_base}/restablecer-clave#token={raw_token}"


async def create_password_reset_token(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    user: User,
    *,
    commit: bool = True,
) -> str | None:
    """Emite un token de un solo uso. Devuelve `None` si se superó el límite por hora.

    Con `commit=False` deja la escritura pendiente para que el llamador la confirme junto
    con el resto de su operación (p. ej. el alta de una cuenta).
    """
    now = _now()
    recent = await session.scalar(
        select(func.count())
        .select_from(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.created_at > now - timedelta(hours=1),
        )
    )
    if recent is not None and recent >= MAX_RESET_REQUESTS_PER_HOUR:
        record_audit(
            session,
            ctx,
            AuditEvent.PASSWORD_RESET_REQUESTED,
            severity=Severity.WARNING,
            target_user_id=user.id,
            details={"sent": False, "reason": "rate_limited"},
        )
        await session.commit()
        return None

    # Un enlace nuevo invalida los anteriores pendientes.
    await session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    raw = generate_token(32)
    expires_at = now + timedelta(minutes=settings.PASSWORD_RESET_TTL_MIN)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=sha256_hex(raw),
            expires_at=expires_at,
            created_by_ip=ctx.ip_address,
        )
    )
    record_audit(
        session,
        ctx,
        AuditEvent.PASSWORD_RESET_REQUESTED,
        target_user_id=user.id,
        details={"sent": True, "expires_at": expires_at.isoformat()},
    )
    if commit:
        await session.commit()
    else:
        await session.flush()
    return raw


async def request_password_reset(
    session: AsyncSession, settings: Settings, ctx: RequestContext, identifier: str
) -> tuple[User, str] | None:
    user = await find_user_by_identifier(session, identifier)
    if user is None or not user.is_active:
        record_audit(
            session,
            ctx,
            AuditEvent.PASSWORD_RESET_REQUESTED,
            target_user_id=user.id if user else None,
            details={"sent": False, "reason": "inactive" if user else "unknown_identifier"},
        )
        await session.commit()
        return None
    raw = await create_password_reset_token(session, settings, ctx, user)
    return (user, raw) if raw else None


async def confirm_password_reset(
    session: AsyncSession,
    ctx: RequestContext,
    raw_token: str,
    new_password: str,
) -> User:
    now = _now()
    result = await session.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == sha256_hex(raw_token))
        .with_for_update()
    )
    token = result.scalars().first()
    user = await get_user(session, token.user_id) if token else None
    if (
        token is None
        or token.used_at is not None
        or token.expires_at <= now
        or user is None
        or not user.is_active
    ):
        record_audit(
            session,
            ctx,
            AuditEvent.PASSWORD_RESET_REJECTED,
            severity=Severity.WARNING,
            target_user_id=user.id if user else None,
            details={
                "reason": "unknown"
                if token is None
                else "used"
                if token.used_at is not None
                else "expired"
                if token.expires_at <= now
                else "inactive"
            },
        )
        await session.commit()
        raise ProblemError(HTTPStatus.BAD_REQUEST, INVALID_RESET_TOKEN)

    try:
        passwords.check_password_policy(new_password, email=user.email)
    except passwords.WeakPasswordError as exc:
        # Se valida antes de consumir el token: una clave débil no quema el enlace.
        raise ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    token.used_at = now
    user.hashed_password = await passwords.hash_password_async(new_password)
    user.password_changed_at = now
    user.failed_login_attempts = 0
    user.locked_until = None
    user.is_verified = True
    await revoke_all_user_sessions(session, user.id, "password_reset")
    record_audit(
        session,
        ctx,
        AuditEvent.PASSWORD_RESET_COMPLETED,
        actor_user_id=user.id,
        target_user_id=user.id,
        details={"sessions_revoked": True},
    )
    await session.commit()
    return user


# --------------------------------------------------------------------------- cuenta propia

PASSWORD_ACTUAL_INCORRECTA = "La contraseña actual no es correcta."


async def change_password(
    session: AsyncSession,
    settings: Settings,
    ctx: RequestContext,
    user: User,
    current: UserSession,
    *,
    current_password: str,
    new_password: str,
) -> None:
    """Cambio de contraseña desde la sesión: exige la actual (un error cuenta para el bloqueo,
    como en el ingreso) y cierra las demás sesiones; la actual sigue abierta."""
    # El bloqueo vale también acá: con una sesión robada no se puede seguir probando la clave.
    if _is_locked(user):
        await passwords.burn_verification_time_async(current_password)
        raise ProblemError(
            HTTPStatus.TOO_MANY_REQUESTS,
            "Demasiados intentos con la contraseña actual: probá de nuevo más tarde.",
        )
    if not await passwords.verify_password_async(user.hashed_password, current_password):
        await _register_failure(session, settings, ctx, user, AuditEvent.LOGIN_FAILED)
        if _is_locked(user):
            # Llegó al bloqueo desde una sesión abierta: se cierran todas, también esta.
            await revoke_all_user_sessions(session, user.id, "password_change_lockout")
            await session.commit()
        raise ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, PASSWORD_ACTUAL_INCORRECTA)
    if new_password == current_password:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "La nueva contraseña tiene que ser distinta de la actual.",
        )
    try:
        passwords.check_password_policy(new_password, email=user.email)
    except passwords.WeakPasswordError as exc:
        raise ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
    now = _now()
    user.hashed_password = await passwords.hash_password_async(new_password)
    user.password_changed_at = now
    user.failed_login_attempts = 0
    user.locked_until = None
    await session.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.is_revoked.is_(False),
            UserSession.session_family_id != current.session_family_id,
        )
        .values(is_revoked=True, revoked_at=now, revoked_reason="password_changed")
    )
    record_audit(
        session,
        ctx,
        AuditEvent.PASSWORD_CHANGED,
        actor_user_id=user.id,
        target_user_id=user.id,
        details={"otras_sesiones_cerradas": True},
    )
    await session.commit()


async def update_profile(
    session: AsyncSession,
    ctx: RequestContext,
    user: User,
    *,
    full_name: str | None,
    phone_number: str | None,
    nombre_editable: bool,
) -> User:
    """Datos de contacto propios. El nombre de un escribano lo lleva el padrón (lo actualiza la
    Caja): no se edita desde la cuenta."""
    antes = {"full_name": user.full_name, "phone_number": user.phone_number}
    if full_name is not None and full_name != user.full_name:
        if not nombre_editable:
            raise ProblemError(
                HTTPStatus.FORBIDDEN,
                "Tu nombre figura en el padrón de escribanos: lo actualiza la Caja.",
            )
        user.full_name = full_name
    user.phone_number = phone_number or None
    despues = {"full_name": user.full_name, "phone_number": user.phone_number}
    if despues != antes:
        record_audit(
            session,
            ctx,
            AuditEvent.USER_PROFILE_UPDATED,
            actor_user_id=user.id,
            target_user_id=user.id,
            old_value=antes,
            new_value=despues,
        )
    await session.commit()
    return user
