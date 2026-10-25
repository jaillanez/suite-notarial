"""Comandos de administración IAM.

python -m app.modules.iam.cli create-admin --email ... --cuit ... --name "..."
python -m app.modules.iam.cli seed-dev        # solo ENVIRONMENT=development
"""

import argparse
import asyncio
import getpass
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, record_audit
from app.common.cuit import InvalidCuitError, check_digit, format_cuit, normalize_cuit
from app.core.config import Environment, get_settings
from app.core.db import get_engine, get_sessionmaker
from app.modules.iam import passwords
from app.modules.iam.models import Role, User, UserRole

CLI_CONTEXT = RequestContext(ip_address=None, user_agent="cli", correlation_id=None, path="cli")

DEV_USERS: tuple[tuple[str, str, str], ...] = (
    ("admin@suite-notarial.example", "Administración Demo", "ROLE_ADMIN"),
    ("caja@suite-notarial.example", "Caja Demo", "ROLE_CAJA"),
    ("tesoreria@suite-notarial.example", "Tesorería Demo", "ROLE_TESORERIA"),
    ("auditor@suite-notarial.example", "Auditoría Demo", "ROLE_AUDITOR"),
    ("escribano@suite-notarial.example", "Escribano Demo", "ROLE_ESCRIBANO"),
)


def _out(message: str) -> None:
    sys.stdout.write(message + "\n")


def synthetic_cuit(seed: int) -> str:
    """CUIT sintético válido (prefijo 20) para datos de desarrollo; nunca uno real."""
    for offset in range(100):
        body = f"20{seed * 100 + offset:08d}"
        digit = check_digit(body)
        if digit is not None:
            return body + str(digit)
    raise RuntimeError("No se pudo generar un CUIT sintético")


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    cuit: str,
    full_name: str,
    password: str,
    role_code: str,
) -> User:
    role = (await session.execute(select(Role).where(Role.code == role_code))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email.lower(),
        cuit=cuit,
        full_name=full_name,
        hashed_password=passwords.hash_password(password),
        is_verified=True,
    )
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id))
    record_audit(
        session,
        CLI_CONTEXT,
        AuditEvent.USER_CREATED,
        target_user_id=user.id,
        new_value={"email": user.email, "cuit": cuit, "full_name": full_name, "roles": [role_code]},
        details={"source": "cli"},
    )
    return user


async def create_admin(email: str, cuit: str, full_name: str) -> int:
    try:
        cuit_digits = normalize_cuit(cuit)
    except InvalidCuitError as exc:
        _out(f"CUIT inválido: {exc}")
        return 2
    password = getpass.getpass("Contraseña: ")
    if password != getpass.getpass("Repetir contraseña: "):
        _out("Las contraseñas no coinciden.")
        return 2
    try:
        passwords.check_password_policy(password, email=email)
    except passwords.WeakPasswordError as exc:
        _out(str(exc))
        return 2
    async with get_sessionmaker()() as session:
        exists = await session.scalar(
            select(User.id).where((User.email == email.lower()) | (User.cuit == cuit_digits))
        )
        if exists:
            _out("Ya existe un usuario con ese correo o CUIT.")
            return 1
        await _create_user(
            session,
            email=email,
            cuit=cuit_digits,
            full_name=full_name,
            password=password,
            role_code="ROLE_ADMIN",
        )
        await session.commit()
    _out(f"Administrador creado: {email}. Al ingresar se le pedirá activar 2FA.")
    return 0


async def seed_dev() -> int:
    settings = get_settings()
    if settings.ENVIRONMENT is not Environment.DEVELOPMENT:
        _out("seed-dev solo se ejecuta con ENVIRONMENT=development.")
        return 1
    if settings.DEV_SEED_PASSWORD is None:
        _out("Definí DEV_SEED_PASSWORD en backend/.env (ver .env.example).")
        return 1
    password = settings.DEV_SEED_PASSWORD.get_secret_value()
    passwords.check_password_policy(password)
    created = 0
    async with get_sessionmaker()() as session:
        for index, (email, name, role) in enumerate(DEV_USERS, start=1):
            if await session.scalar(select(User.id).where(User.email == email)):
                continue
            cuit = synthetic_cuit(index)
            await _create_user(
                session, email=email, cuit=cuit, full_name=name, password=password, role_code=role
            )
            _out(f"  {role:<15} {email:<32} CUIT {format_cuit(cuit)}")
            created += 1
        await session.commit()
    _out(f"Usuarios de desarrollo creados: {created} (contraseña: DEV_SEED_PASSWORD).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iam")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="Crea un usuario administrador")
    admin.add_argument("--email", required=True)
    admin.add_argument("--cuit", required=True)
    admin.add_argument("--name", required=True)
    sub.add_parser("seed-dev", help="Crea usuarios de demostración (solo desarrollo)")
    args = parser.parse_args(argv)

    async def run() -> int:
        try:
            if args.command == "create-admin":
                return await create_admin(args.email, args.cuit, args.name)
            return await seed_dev()
        finally:
            await get_engine().dispose()

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
