"""Consola de la migración: `python -m app.modules.migracion.cli <comando>`.

sintetico   --salida DIR [--registros N] [--defectos]    lote de prueba (nunca datos reales)
simulacro   --lote DIR --operador EMAIL [--homologacion JSON]
definitiva  --lote DIR --operador EMAIL --homologacion JSON
respaldo    --salida ARCHIVO                             pg_dump del esquema (rol dueño)
reversa     --respaldo ARCHIVO --confirmo-reversa        vuelve la base al respaldo
ensayo      --salida DIR [--registros N]                 ensayo cronometrado (base de ensayo)
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.modules.migracion import ensayo, reversa, service, sintetico
from app.modules.migracion.catalog import ModoCorrida
from app.modules.migracion.formato import FormatoInvalidoError
from app.modules.migracion.homologacion import HomologacionInvalidaError


def _out(mensaje: str) -> None:
    sys.stdout.write(mensaje + "\n")


def _err(mensaje: str) -> None:
    sys.stderr.write(mensaje + "\n")


def _url_ensayo(url: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/suite_notarial_ensayo"


def _resumen(resultado: service.Resultado) -> None:
    informe = resultado.informe
    _out(f"Corrida {resultado.corrida_id}: {resultado.estado.value}")
    _out(f"Cuadra: {'sí' if resultado.cuadra else 'NO'}")
    for e in informe["entidades"]:
        linea = (
            f"  {e['entidad']:<11} control {e['control_filas']:>6} · leídas {e['leidas']:>6} · "
            f"cargadas {e['cargadas']:>6} · rechazadas {e['rechazadas']:>5}"
        )
        if "importe_cargado" in e:
            linea += f" · importe control {e['control_importe']} / cargado {e['importe_cargado']}"
        _out(linea)
    _out(
        f"Observaciones: {resultado.bloqueantes} bloqueantes, {resultado.advertencias} advertencias"
    )
    for codigo, cantidad in informe["observaciones_por_codigo"].items():
        _out(f"  {codigo}: {cantidad}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="migracion")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("sintetico", help="Genera un lote de prueba en el formato de intercambio")
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--registros", type=int, default=20)
    p.add_argument("--semilla", type=int, default=42)
    p.add_argument("--defectos", action="store_true")
    for nombre in ("simulacro", "definitiva"):
        p = sub.add_parser(nombre)
        p.add_argument("--lote", type=Path, required=True)
        p.add_argument(
            "--operador", required=True, help="Correo de un usuario con migracion:ejecutar"
        )
        p.add_argument("--homologacion", type=Path, required=nombre == "definitiva")
        p.add_argument("--json", action="store_true", help="Imprime el informe completo")
    p = sub.add_parser("respaldo")
    p.add_argument("--salida", type=Path, required=True)
    p = sub.add_parser("reversa")
    p.add_argument("--respaldo", type=Path, required=True)
    p.add_argument("--confirmo-reversa", action="store_true")
    p = sub.add_parser("ensayo")
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--registros", type=int, default=30)
    p.add_argument("--periodos", type=int, default=12, help="Boletas mensuales por registro")
    args = parser.parse_args(argv)
    settings = get_settings()
    owner_url = settings.migrations_database_url

    if args.comando == "sintetico":
        resumen = sintetico.generar(
            args.salida, registros=args.registros, semilla=args.semilla, defectos=args.defectos
        )
        _out(f"Lote sintético en {args.salida}: {resumen}")
        return 0
    if args.comando == "respaldo":
        tamano = reversa.respaldar(owner_url, args.salida)
        _out(f"Respaldo en {args.salida} ({tamano:,} bytes).".replace(",", "."))
        return 0
    if args.comando == "reversa":
        if not args.confirmo_reversa:
            _err(
                "La reversa reemplaza TODOS los datos por los del respaldo: "
                "agregá --confirmo-reversa."
            )
            return 2
        reversa.restaurar(owner_url, args.respaldo)
        _out(f"Base restaurada al respaldo {args.respaldo}.")
        return 0
    if args.comando == "ensayo":
        informe = asyncio.run(
            ensayo.ensayar(
                _url_ensayo(owner_url),
                _url_ensayo(str(settings.DATABASE_URL)),
                args.salida,
                registros=args.registros,
                periodos=args.periodos,
            )
        )
        _out(f"Ensayo {informe.resultado}: reversa en {informe.reversa_s:.1f} s.")
        _out(f"Informe: {args.salida / 'informe-ensayo.md'}")
        return 0

    modo = ModoCorrida.SIMULACRO if args.comando == "simulacro" else ModoCorrida.DEFINITIVA

    async def correr() -> int:
        try:
            resultado = await service.correr(
                args.lote,
                modo,
                args.operador,
                homologacion_ruta=args.homologacion,
                maker=get_sessionmaker(),
            )
        except (service.MigracionError, FormatoInvalidoError, HomologacionInvalidaError) as exc:
            _err(str(exc))
            return 2
        finally:
            await get_engine().dispose()
        if args.json:
            _out(json.dumps(resultado.informe, ensure_ascii=False, indent=2))
        else:
            _resumen(resultado)
        return 0 if resultado.cuadra else 1

    return asyncio.run(correr())


if __name__ == "__main__":
    raise SystemExit(main())
