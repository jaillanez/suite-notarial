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
    async with get_sessionmaker()() as session:
        await _seed_padron_demo(session)
    async with get_sessionmaker()() as session:
        await _seed_parametros_demo(session)
    async with get_sessionmaker()() as session:
        await _seed_vencimientos(session)
    async with get_sessionmaker()() as session:
        await _seed_lineas_prestamo(session)
    return 0


async def _seed_lineas_prestamo(session: AsyncSession) -> None:
    """Líneas de crédito de EJEMPLO para probar en desarrollo.

    TODO(negocio): tasas, plazos, montos y topes los fija el Directorio de la Caja. Estos valores
    son ilustrativos y quedan marcados como «a confirmar» (es_ejemplo).
    """
    from decimal import Decimal

    from app.modules.prestamos.models import Linea

    if await session.scalar(select(Linea.id).limit(1)):
        _out("Líneas de préstamo: ya existen, no se modifican.")
        return
    ejemplos = (
        ("LINEA_COMUN", "Línea común", "FRANCES", 12, 36, "100000", "5000000", "48", "30", False),
        (
            "RECIEN_MATRICULADOS",
            "Recién matriculados",
            "FRANCES",
            12,
            60,
            "100000",
            "3000000",
            "36",
            "30",
            False,
        ),
        (
            "EXTRAORDINARIA",
            "Asistencial extraordinaria",
            "ALEMAN",
            6,
            24,
            "50000",
            "2000000",
            "24",
            "25",
            True,
        ),
    )
    for codigo, nombre, sistema, pmin, pmax, mmin, mmax, tna, afect, garante in ejemplos:
        session.add(
            Linea(
                codigo=codigo,
                nombre=nombre,
                descripcion="Valores de ejemplo: a confirmar por el Directorio.",
                sistema=sistema,
                plazo_minimo=pmin,
                plazo_maximo=pmax,
                monto_minimo=Decimal(mmin),
                monto_maximo=Decimal(mmax),
                tna=Decimal(tna),
                afectacion_maxima=Decimal(afect),
                requiere_garante=garante,
                es_ejemplo=True,
            )
        )
    await session.commit()
    _out(f"Líneas de préstamo de ejemplo: {len(ejemplos)} (a confirmar).")


async def _seed_vencimientos(session: AsyncSession) -> None:
    """Calendario de vencimientos 2026 relevado del sistema en uso."""
    from app.modules.ddjj.models import Vencimiento
    from app.modules.parametros.sistema_actual import VENCIMIENTOS_2026

    if await session.scalar(select(Vencimiento.id).limit(1)):
        _out("Vencimientos: ya existen, no se modifican.")
        return
    for mes, fecha in VENCIMIENTOS_2026.items():
        session.add(Vencimiento(periodo=f"2026-{mes:02d}", fecha_vencimiento=fecha))
    await session.commit()
    _out(f"Vencimientos 2026: {len(VENCIMIENTOS_2026)} períodos.")


async def _seed_parametros_demo(session: AsyncSession) -> None:
    """Parámetros 2026 relevados del sistema en uso (ver parametros/sistema_actual.py).

    En desarrollo se cargan ya aprobados para poder calcular; los de significado dudoso quedan
    marcados como ejemplo. En producción se cargan como propuestas que aprueba la Caja.
    """
    from datetime import UTC, datetime

    from app.modules.parametros.models import Concepto, Vigencia
    from app.modules.parametros.sistema_actual import CONCEPTOS, FUENTE

    if await session.scalar(select(Concepto.id).limit(1)):
        _out("Parámetros: ya existen, no se modifican.")
        return
    admin = await session.scalar(select(User).where(User.email == DEV_USERS[0][0]))
    aprobador = await session.scalar(select(User).where(User.email == DEV_USERS[2][0]))
    if admin is None or aprobador is None:
        return
    vigencias = 0
    for relevado in CONCEPTOS:
        concepto = Concepto(
            id=uuid.uuid4(),
            codigo=relevado.codigo,
            nombre=relevado.nombre,
            tipo=relevado.tipo.value,
            descripcion=relevado.descripcion,
            created_by_user_id=admin.id,
        )
        session.add(concepto)
        for version, tramo in enumerate(relevado.tramos, start=1):
            session.add(
                Vigencia(
                    concepto_id=concepto.id,
                    version=version,
                    fecha_desde=tramo.desde,
                    fecha_hasta=tramo.hasta,
                    **tramo.valores,
                    es_ejemplo=tramo.a_confirmar,
                    estado="VIGENTE",
                    resolucion_respaldo="Sistema actual (sin resolución)",
                    motivo=f"{FUENTE}. TODO(negocio): citar la resolución que lo dispuso.",
                    created_by_user_id=admin.id,
                    aprobado_por_user_id=aprobador.id,
                    fecha_aprobacion=datetime.now(UTC),
                )
            )
            vigencias += 1
    await session.commit()
    _out(
        f"Parámetros del sistema actual: {len(CONCEPTOS)} conceptos, {vigencias} vigencias "
        "(la tasa de mora queda marcada a confirmar)."
    )


DEMO_ESCRIBANOS: tuple[tuple[str, str, int, str | None, int | None], ...] = (
    # apellido, nombre, matrícula, cargo, número de registro
    ("Demo", "Escribano", 101, "TITULAR", 1),
    ("Albarracín", "Lucía", 102, "ADSCRIPTO", 1),
    ("Quiroga", "Martín", 103, "TITULAR", 2),
    ("Videla", "Carolina", 104, None, None),
    ("Godoy", "Ramiro", 105, "ADSCRIPTO", 2),
)


async def _seed_padron_demo(session: AsyncSession) -> None:
    """Padrón sintético para probar la Suite. Nombres y CUIT inventados; nunca datos reales."""
    from datetime import date

    from app.modules.padron.catalog import Cargo, EstadoMatricula, EstadoRegistro
    from app.modules.padron.models import (
        Adscripcion,
        Circunscripcion,
        Escribano,
        Persona,
        RegistroNotarial,
    )

    if await session.scalar(select(Circunscripcion.id).limit(1)):
        _out("Padrón de demostración: ya existe, no se modifica.")
        return
    circ = Circunscripcion(
        id=uuid.uuid4(), nombre="Circunscripción Demo", descripcion="Dato de demostración"
    )
    session.add(circ)
    registros: dict[int, RegistroNotarial] = {}
    for numero, departamento in ((1, "Capital"), (2, "Rivadavia"), (3, "Rawson")):
        registros[numero] = RegistroNotarial(
            id=uuid.uuid4(),
            numero_registro=numero,
            nombre_fantasia=f"Escribanía Demo {numero}",
            circunscripcion_id=circ.id,
            departamento=departamento,
            domicilio_legal=f"Calle Demo {numero * 100}",
            estado=EstadoRegistro.VACANTE.value,
        )
        session.add(registros[numero])
    escribano_user = await session.scalar(
        select(User).where(User.email == "escribano@suite-notarial.example")
    )
    for index, (apellido, nombre, matricula, cargo, nro) in enumerate(DEMO_ESCRIBANOS):
        demo_user = escribano_user if index == 0 else None
        persona = Persona(
            id=uuid.uuid4(),
            cuit=demo_user.cuit if demo_user else synthetic_cuit(10 + index),
            tipo_documento="DNI",
            numero_documento=(demo_user.cuit if demo_user else synthetic_cuit(10 + index))[2:10],
            apellido=apellido,
            nombre=nombre,
            email=demo_user.email if demo_user else None,
        )
        session.add(persona)
        escribano = Escribano(
            id=uuid.uuid4(),
            persona_id=persona.id,
            user_id=demo_user.id if demo_user else None,
            matricula_numero=matricula,
            fecha_matriculacion=date(2015, 3, 1),
            estado_matricula=EstadoMatricula.ACTIVO.value,
        )
        session.add(escribano)
        if cargo and nro:
            session.add(
                Adscripcion(
                    escribano_id=escribano.id,
                    registro_id=registros[nro].id,
                    cargo=cargo,
                    fecha_desde=date(2020, 1, 2),
                    is_current=True,
                )
            )
            if cargo == Cargo.TITULAR:
                registros[nro].estado = EstadoRegistro.ACTIVO.value
    await session.commit()
    _out("Padrón de demostración: 1 circunscripción, 3 registros, 5 escribanos.")


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
