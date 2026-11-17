"""Consola del botón de pagos Supervielle: configuración, prueba de acceso y conciliación diaria.

- `estado`: qué variables de configuración faltan y a qué ambiente del banco apunta (no muestra
  ningún secreto).
- `probar`: pide un token al banco (confirma las credenciales). Con `--publicar-prueba`, solo en
  el ambiente de pruebas del banco, publica una deuda de $10 que vence mañana y muestra su link,
  para pagarla con las tarjetas de prueba del banco; con `--hash` consulta su estado.
- `conciliar`: recupera los pagos cuyo aviso se perdió. Lo programa deploy/instalar-cron.sh.

python -m app.modules.pagos.supervielle_cli estado
python -m app.modules.pagos.supervielle_cli probar [--publicar-prueba | --hash HASH]
python -m app.modules.pagos.supervielle_cli conciliar [--dias 3]
"""

import argparse
import asyncio
import sys
import time
from datetime import timedelta
from decimal import Decimal

from app.common.audit import RequestContext
from app.common.dates import today_local
from app.core.config import get_settings
from app.modules.pagos import supervielle

CLI_CONTEXT = RequestContext(
    ip_address=None, user_agent="cli", correlation_id=None, path="cli:pagos:supervielle"
)


def _escribir(texto: str) -> None:
    sys.stdout.write(f"{texto}\n")


def estado() -> int:
    s = get_settings()
    ambiente = "PRUEBAS" if supervielle.es_ambiente_de_pruebas() else "PRODUCCIÓN"
    _escribir(f"ambiente del banco: {ambiente}")
    _escribir(f"  API:   {s.SUPERVIELLE_API_URL}")
    _escribir(f"  token: {s.SUPERVIELLE_AUTH_URL}")
    _escribir(f"  X-Forwarded-Host: {s.SUPERVIELLE_FORWARDED_HOST}")
    _escribir(f"convenio: {s.SUPERVIELLE_CONVENIO or '—'}")
    faltan = supervielle.faltantes()
    if faltan:
        _escribir("faltan (el botón no se ofrece): " + ", ".join(faltan))
        return 1
    _escribir("configuración completa: el botón se ofrece en las boletas")
    return 0


async def probar(*, publicar: bool, hash_: str | None) -> int:
    if estado() != 0:
        return 1
    try:
        await supervielle.probar_acceso()
        _escribir("acceso: OK (el banco entregó el token)")
        if publicar:
            if not supervielle.es_ambiente_de_pruebas():
                _escribir("--publicar-prueba solo se usa con el ambiente de pruebas del banco")
                return 2
            # Fuera del rango de la secuencia de la Suite y distinto en cada prueba.
            numero = 9_000_000_000_000 + int(time.time())
            publicacion = await supervielle.publicar(
                id_publicacion=numero,
                importe=Decimal("10.00"),
                vence=today_local() + timedelta(days=1),
                nombre="Prueba de integración",
                descripcion="Caja Notarial · prueba de integración del botón de pagos",
                identificadores=["prueba-integracion"],
            )
            _escribir(f"publicada: hash {publicacion.hash}")
            _escribir(f"link de pago: {publicacion.link_pago}")
        if hash_:
            pagos = await supervielle.pagos_de(hash_)
            if not pagos:
                _escribir("la publicación no tiene pagos todavía")
            for p in pagos:
                importe = f"${p.importe:.2f}" if p.importe is not None else "—"
                _escribir(f"pago {p.id}: {p.estado.value} · {p.medio_pago or '—'} · {importe}")
    except supervielle.SupervielleError as exc:
        _escribir(f"ERROR: {exc}")
        return 1
    return 0


async def conciliar(dias: int) -> int:
    from app.core.db import get_sessionmaker
    from app.core.errors import ProblemError
    from app.modules.pagos import supervielle_service

    if not supervielle.configurado():
        # Antes de cargar las credenciales, la tarea programada no tiene nada que hacer.
        _escribir("botón Supervielle sin configurar: nada que conciliar")
        return 0
    hasta = today_local()
    desde = hasta - timedelta(days=dias)
    try:
        async with get_sessionmaker()() as session:
            r = await supervielle_service.conciliar(session, CLI_CONTEXT, desde, hasta)
    except ProblemError as exc:
        _escribir(f"ERROR: {exc.detail}")
        return 1
    rango = f"{desde.isoformat()} a {hasta.isoformat()}"
    _escribir(f"conciliación {rango}: {r.consultadas} consultadas")
    for numero, antes, despues in r.actualizadas:
        _escribir(f"  publicación {numero}: {antes} -> {despues}")
    for hash_, pago_id, importe in r.ajenos:
        _escribir(f"  pago {pago_id} (${importe}) de una publicación que no armó la Suite: {hash_}")
    for error in r.errores:
        _escribir(f"  ERROR {error}")
    return 1 if r.errores else 0


def main(argumentos: list[str] | None = None) -> int:
    lector = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = lector.add_subparsers(dest="comando", required=True)
    sub.add_parser("estado", help="Qué falta configurar y a qué ambiente apunta")
    p = sub.add_parser("probar", help="Prueba el acceso al banco")
    grupo = p.add_mutually_exclusive_group()
    grupo.add_argument("--publicar-prueba", action="store_true")
    grupo.add_argument("--hash", help="Consulta el estado de una publicación")
    p = sub.add_parser("conciliar", help="Recupera los pagos cuyo aviso se perdió")
    p.add_argument("--dias", type=int, default=3, help="Días hacia atrás de la rendición")
    args = lector.parse_args(argumentos)
    if args.comando == "estado":
        return estado()
    if args.comando == "probar":
        return asyncio.run(probar(publicar=args.publicar_prueba, hash_=args.hash))
    # Registra todos los modelos: corriendo solo, SQLAlchemy no resolvería las relaciones.
    import app.db.models  # noqa: F401

    return asyncio.run(conciliar(max(1, min(args.dias, 60))))


if __name__ == "__main__":
    raise SystemExit(main())
