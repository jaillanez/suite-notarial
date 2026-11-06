"""Carga de la planilla histórica de aportes y puntos (Ley 7231).

    python -m app.modules.previsional.cargar_puntos --planilla ARCHIVO.xls --operador EMAIL
        [--simular] [--origen TEXTO] [--detalle ARCHIVO.csv]
    python -m app.modules.previsional.cargar_puntos --revincular --operador EMAIL [--simular]

- `--simular` hace todo dentro de una transacción que se revierte: muestra el informe y no deja
  nada cargado.
- La consola nunca muestra nombres de afiliados: identifica por fila de la planilla. El detalle
  con nombres (redondeos, vínculos aproximados, sin vincular) va a `--detalle`, un CSV que elige
  el operador y que debe tratarse como dato personal.
- Idempotente: lo ya cargado que coincide se saltea; lo que difiere no se sobreescribe.
"""

import argparse
import asyncio
import csv
import sys
from pathlib import Path

from app.common.audit import RequestContext
from app.core.db import get_engine, get_sessionmaker
from app.modules.previsional import service
from app.modules.previsional.planilla import Planilla, PlanillaInvalidaError, leer_planilla

CONTEXTO = RequestContext(
    ip_address=None, user_agent="cli cargar_puntos", correlation_id=None, path="cli"
)


def _out(mensaje: str) -> None:
    sys.stdout.write(mensaje + "\n")


def _err(mensaje: str) -> None:
    sys.stderr.write(mensaje + "\n")


def _informe_planilla(planilla: Planilla) -> None:
    anios = [e.anio for e in planilla.ejercicios]
    _out(f"Ejercicios leídos: {len(anios)} ({min(anios)} a {max(anios)})")
    _out(f"Afiliados leídos: {planilla.afiliados}")
    _out(f"Filas de puntos (un afiliado en un ejercicio con datos): {len(planilla.puntos)}")
    _out(f"Pares vacíos o en cero omitidos: {planilla.celdas_vacias}")
    if planilla.filas_sin_nombre:
        filas = ", ".join(map(str, planilla.filas_sin_nombre))
        _out(f"Filas con cifras y sin nombre (no se cargan): {filas}")
    if planilla.filas_repetidas:
        filas = ", ".join(map(str, planilla.filas_repetidas))
        _out(f"Filas con nombre repetido (no se cargan): {filas}")
    _out(f"Puntos con más de 6 decimales (se guardan con 6): {planilla.puntos_redondeados}")
    _out(f"Valores redondeados a la escala de la base: {len(planilla.redondeos)}")
    for aviso in planilla.avisos:
        _out(f"  Aviso: {aviso}")
    _out("Cuadratura por ejercicio (total de la hoja vs. suma de los afiliados):")
    for e in planilla.ejercicios:
        suma = planilla.suma_aportes[e.anio]
        marca = "" if suma == e.total_aportes else f"  diferencia {suma - e.total_aportes}"
        _out(
            f"  {e.anio}: total {e.total_aportes} · suma {suma}{marca} · "
            f"puntos {planilla.suma_puntos[e.anio]} · afiliados {e.cantidad_afiliados}"
        )


def _redondeos_consola(planilla: Planilla) -> None:
    _out("Detalle de redondeos (fila · ejercicio · campo: planilla → base):")
    for r in planilla.redondeos:
        _out(f"  fila {r.fila} · {r.anio} · {r.campo}: {r.original} → {r.guardado}")


def _escribir_detalle(ruta: Path, planilla: Planilla | None, res: service.ResultadoCarga) -> None:
    nombres = {p.fila: p.nombre for p in planilla.puntos} if planilla else {}
    with ruta.open("w", newline="", encoding="utf-8") as archivo:
        w = csv.writer(archivo, delimiter=";")
        w.writerow(["tipo", "fila", "ejercicio", "nombre", "detalle"])
        if planilla:
            for r in planilla.redondeos:
                w.writerow(
                    [
                        "redondeo",
                        r.fila,
                        r.anio,
                        nombres.get(r.fila, ""),
                        f"{r.campo}: {r.original} → {r.guardado}",
                    ]
                )
        for d in res.diferencias:
            cambios = ", ".join(f"{k}: base {a} / planilla {b}" for k, (a, b) in d.campos.items())
            w.writerow(["diferencia", d.fila or "", d.anio, nombres.get(d.fila or 0, ""), cambios])
        v = res.vinculacion
        for nombre, escribano_id in v.aproximadas:
            w.writerow(["sugerencia_aproximada", "", "", nombre, f"escribano {escribano_id}"])
        for nombre in v.ambiguas:
            w.writerow(["vinculo_ambiguo", "", "", nombre, "más de un escribano posible"])
        for nombre in v.sin_vincular:
            w.writerow(["sin_vincular", "", "", nombre, ""])


def _informe_resultado(res: service.ResultadoCarga) -> None:
    _out(f"Ejercicios nuevos: {res.ejercicios_nuevos} · iguales: {res.ejercicios_iguales}")
    _out(f"Filas de puntos nuevas: {res.puntos_nuevos} · iguales: {res.puntos_iguales}")
    if res.diferencias:
        n = len(res.diferencias)
        _out(f"Datos ya cargados que difieren de la planilla (NO se sobreescriben): {n}")
        for d in res.diferencias:
            donde = f"fila {d.fila} · " if d.fila else ""
            _out(f"  {donde}{d.anio}: {', '.join(d.campos)}")
    _informe_vinculacion(res.vinculacion)


def _informe_vinculacion(v: service.ResultadoVinculacion) -> None:
    _out("Vínculo con el padrón (nombres distintos de la planilla):")
    _out(f"  exactos: {v.exactas}")
    _out(f"  aproximados (solo sugerencia, NO vinculados; a revisar): {len(v.aproximadas)}")
    _out(f"  con el vínculo de otros ejercicios (exacto o heredado a confirmar): {v.heredadas}")
    _out(f"  ambiguos (más de un escribano posible): {len(v.ambiguas)}")
    _out(f"  sin vincular: {len(v.sin_vincular)}")
    _out(f"  filas vinculadas en esta corrida: {v.filas_vinculadas}")


async def _correr(args: argparse.Namespace) -> int:
    planilla: Planilla | None = None
    if not args.revincular:
        planilla = leer_planilla(args.planilla)
        _informe_planilla(planilla)
        if not args.detalle:
            _redondeos_consola(planilla)
    origen = args.origen or (
        f"Planilla histórica de la Caja «{args.planilla.name}»" if args.planilla else ""
    )
    try:
        async with get_sessionmaker()() as session:
            actor = await service.operador(session, args.operador)
            if planilla is not None:
                resultado = await service.cargar(session, planilla, actor, origen, CONTEXTO)
            else:
                resultado = service.ResultadoCarga(
                    vinculacion=await service.revincular_auditado(session, actor, CONTEXTO)
                )
            if planilla is not None:
                _informe_resultado(resultado)
            else:
                _informe_vinculacion(resultado.vinculacion)
            if args.detalle:
                _escribir_detalle(args.detalle, planilla, resultado)
                _out(f"Detalle con nombres en {args.detalle} (dato personal: no compartir).")
            if args.simular:
                await session.rollback()
                _out("SIMULACIÓN: no se guardó nada.")
            else:
                await session.commit()
                _out("Carga confirmada.")
    except service.CargaError as exc:
        _err(str(exc))
        return 2
    finally:
        await get_engine().dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cargar_puntos", description=__doc__.splitlines()[0])
    parser.add_argument("--planilla", type=Path, help="Planilla .xls o .xlsx (hoja «Actualizada»)")
    parser.add_argument(
        "--operador", required=True, help="Correo de un usuario con el permiso puntos:manage"
    )
    parser.add_argument("--simular", action="store_true", help="No guarda nada (revierte)")
    parser.add_argument(
        "--revincular",
        action="store_true",
        help="No lee planilla: reintenta vincular los puntos sin escribano con el padrón",
    )
    parser.add_argument("--origen", help="Texto de origen que queda en cada fila cargada")
    parser.add_argument(
        "--detalle", type=Path, help="CSV con el detalle por nombre (contiene datos personales)"
    )
    args = parser.parse_args(argv)
    if bool(args.planilla) == bool(args.revincular):
        parser.error("Indicá --planilla o --revincular (uno de los dos).")
    try:
        return asyncio.run(_correr(args))
    except PlanillaInvalidaError as exc:
        _err(f"Planilla inválida: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
