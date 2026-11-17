"""Comandos de consola del padrón. Todo queda auditado a nombre de `--operador`.

python -m app.modules.padron.cli registro-prueba --email ... --operador ... [--desde AAAA-MM-DD]
python -m app.modules.padron.cli baja-registro-prueba --operador ... [--numero 9999]
python -m app.modules.padron.cli vincular-cuenta --email ... --cuit ... --operador ...
"""

import argparse
import asyncio
import sys
from datetime import date

# Registra todos los modelos: corriendo solo, SQLAlchemy no resolvería las relaciones.
import app.db.models  # noqa: F401
from app.common.audit import RequestContext
from app.common.cuit import InvalidCuitError, format_cuit, normalize_cuit
from app.common.dates import today_local
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.errors import ProblemError
from app.modules.iam.models import User
from app.modules.padron import prueba

CLI_CONTEXT = RequestContext(
    ip_address=None, user_agent="cli", correlation_id=None, path="cli/padron"
)


def _out(message: str) -> None:
    sys.stdout.write(message + "\n")


async def _operador(email: str, session_email: str | None = None) -> User:
    async with get_sessionmaker()() as session:
        operador = await prueba.cuenta_por_email(session, email)
    if not operador.is_active:
        raise prueba.PruebaError(f"La cuenta del operador {email} está suspendida.")
    if session_email is not None and operador.email == session_email.strip().lower():
        raise prueba.PruebaError("El operador no puede ser la misma cuenta que se vincula.")
    return operador


async def registro_prueba(email: str, operador_email: str, desde: date, numero: int) -> int:
    operador = await _operador(operador_email, email)
    async with get_sessionmaker()() as session:
        cuenta = await prueba.cuenta_por_email(session, email)
        hecho = await prueba.crear_registro_prueba(
            session,
            CLI_CONTEXT,
            operador,
            cuenta,
            entorno=get_settings().ENVIRONMENT,
            desde=desde,
            numero_registro=numero,
        )
    _out(
        f"Registro de prueba {hecho.numero_registro} creado: {cuenta.email} es su titular "
        f"desde el {desde:%d/%m/%Y} y ya puede cargar DDJJ."
    )
    return 0


async def baja_registro_prueba(operador_email: str, numero: int) -> int:
    operador = await _operador(operador_email)
    async with get_sessionmaker()() as session:
        hecho = await prueba.baja_registro_prueba(
            session,
            CLI_CONTEXT,
            operador,
            entorno=get_settings().ENVIRONMENT,
            hoy=today_local(),
            numero_registro=numero,
        )
    _out(
        f"Registro de prueba {hecho.numero_registro} dado de baja: registro cerrado, escribano "
        "ficticio cesante y cuenta desvinculada (sigue activa). Las DDJJ de prueba quedan."
    )
    return 0


async def vincular_cuenta(email: str, cuit: str, operador_email: str) -> int:
    try:
        cuit_digits = normalize_cuit(cuit)
    except InvalidCuitError as exc:
        _out(f"CUIT inválido: {exc}")
        return 2
    operador = await _operador(operador_email, email)
    async with get_sessionmaker()() as session:
        cuenta = await prueba.cuenta_por_email(session, email)
        escribano = await prueba.vincular_cuenta(
            session, CLI_CONTEXT, operador, cuenta, cuit_digits
        )
        persona = escribano.persona
    _out(
        f"Cuenta {cuenta.email} vinculada a {persona.apellido}, {persona.nombre} "
        f"(CUIT {format_cuit(cuit_digits)})."
    )
    return 0


def _fecha(valor: str) -> date:
    try:
        return date.fromisoformat(valor)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("usá el formato AAAA-MM-DD") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="padron")
    sub = parser.add_subparsers(dest="command", required=True)

    crear = sub.add_parser(
        "registro-prueba", help="Crea un registro ficticio y vincula la cuenta como titular"
    )
    crear.add_argument("--email", required=True, help="Cuenta de escribano que lo opera")
    crear.add_argument("--operador", required=True, help="Cuenta que figura en la auditoría")
    crear.add_argument(
        "--desde",
        type=_fecha,
        default=date(today_local().year, 1, 1),
        help="Inicio del cargo (por defecto, 1 de enero del año en curso)",
    )
    crear.add_argument("--numero", type=int, default=prueba.NUMERO_REGISTRO_PRUEBA)

    baja = sub.add_parser("baja-registro-prueba", help="Baja lógica del registro de prueba")
    baja.add_argument("--operador", required=True, help="Cuenta que figura en la auditoría")
    baja.add_argument("--numero", type=int, default=prueba.NUMERO_REGISTRO_PRUEBA)

    vincular = sub.add_parser(
        "vincular-cuenta", help="Vincula una cuenta existente con su escribano del padrón"
    )
    vincular.add_argument("--email", required=True)
    vincular.add_argument("--cuit", required=True, help="CUIT del escribano (y de la cuenta)")
    vincular.add_argument("--operador", required=True, help="Cuenta que figura en la auditoría")

    args = parser.parse_args(argv)

    async def run() -> int:
        try:
            if args.command == "registro-prueba":
                return await registro_prueba(args.email, args.operador, args.desde, args.numero)
            if args.command == "baja-registro-prueba":
                return await baja_registro_prueba(args.operador, args.numero)
            return await vincular_cuenta(args.email, args.cuit, args.operador)
        except prueba.PruebaError as exc:
            _out(str(exc))
            return 1
        except ProblemError as exc:
            _out(exc.detail or exc.title)
            return 1
        finally:
            await get_engine().dispose()

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
