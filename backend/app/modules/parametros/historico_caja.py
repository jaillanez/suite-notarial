"""Valores históricos de los aportes desde el cuadro de la Caja (Fase 10).

`python -m app.modules.parametros.historico_caja --planilla XLSX --propone EMAIL
[--aprueba EMAIL] [--simular]`

Fuente: «Historico de Valores de aportes.xlsx», hoja «cuadro historico», entregada por la Caja
el 05/11/2026. Cada columna es un período (mes devengado) con su vencimiento; el cuadro sólo
trae una columna cuando algún valor cambia, así que cada valor rige desde su período hasta el
anterior al cambio siguiente. La planilla expresa el porcentaje como fracción (0,004) y el
sistema como porcentaje (0,40).

Se cargan sólo los meses anteriores a lo que el sistema ya tiene (nunca pisa una vigencia): cada
tramo entra como propuesta, con su respaldo y auditoría, y lo aprueba otra persona
(`--aprueba`, cuatro ojos). También completa el calendario de vencimientos que falte.
TODO(negocio): el cuadro no cita resoluciones; se respalda en el cuadro mismo.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import RequestContext
from app.modules.parametros.schemas import VigenciaIn

RESPALDO = "Cuadro histórico de la Caja (05/11/2026)"
MOTIVO = (
    "Valor histórico tomado del cuadro de aportes mínimos y máximos que entregó la Caja el "
    "05/11/2026. TODO(negocio): citar la resolución que lo dispuso."
)
CONTEXTO = RequestContext(ip_address=None, user_agent="cli", correlation_id=None, path="cli")

MESES = {
    nombre: numero
    for numero, nombre in enumerate(
        (
            "ENERO",
            "FEBRERO",
            "MARZO",
            "ABRIL",
            "MAYO",
            "JUNIO",
            "JULIO",
            "AGOSTO",
            "SEPTIEMBRE",
            "OCTUBRE",
            "NOVIEMBRE",
            "DICIEMBRE",
        ),
        start=1,
    )
}

# Fila del cuadro (texto de la primera columna, sin tildes) → (concepto, campo de la vigencia).
FILAS: tuple[tuple[str, str, str], ...] = (
    ("APORTE VARIABLE POR ESCRITURAS - % S/VALOR", "APORTE_ESCRITURA", "porcentaje"),
    ("APORTE VARIABLE MINIMO POR ESCRITURAS", "APORTE_ESCRITURA", "monto_minimo"),
    ("APORTE VARIABLE MAXIMO POR ESCRITURAS", "APORTE_ESCRITURA", "monto_maximo"),
    ("APORTES FIJOS POR ACTAS Y PODERES", "APORTE_FIJO_ACTAS_PODERES", "monto_fijo"),
    ("APORTE FIJO POR OTROS ACTOS", "APORTE_FIJO_OTROS_ACTOS", "monto_fijo"),
    ("APORTE PREVISIONAL MINIMO MENSUAL", "APORTE_MINIMO_MENSUAL", "monto_fijo"),
    ("APORTE MEDICO ASISTENCIAL MENSUAL", "APORTE_MEDICO_ASISTENCIAL", "monto_fijo"),
)
SIN_TOPE = "SIN MAXIMO"
CENTAVO, DIEZMILESIMO = Decimal("0.01"), Decimal("0.0001")


class CuadroInvalidoError(ValueError):
    pass


@dataclass(frozen=True)
class Redondeo:
    codigo: str
    periodo: date
    campo: str
    original: Decimal
    redondeado: Decimal


@dataclass(frozen=True)
class Tramo:
    codigo: str
    desde: date
    hasta: date | None
    valores: dict[str, Decimal | None]


def _normal(valor: object) -> str:
    texto = " ".join(str(valor or "").split()).upper()
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def _periodo(rotulo: object, vencimiento: date) -> date:
    """«Abril (*)», «Enero 2025»… El año sale del rótulo o, si no lo trae, del vencimiento
    (que cae en el mes siguiente o el otro)."""
    palabras = _normal(rotulo).replace("(", " ").replace(")", " ").replace("*", " ").split()
    mes = next((MESES[p] for p in palabras if p in MESES), None)
    if mes is None:
        raise CuadroInvalidoError(f"Período ilegible: «{rotulo}».")
    anio = next((int(p) for p in palabras if p.isdigit() and len(p) == 4), None)
    if anio is None:
        anio = vencimiento.year if mes <= vencimiento.month else vencimiento.year - 1
    return date(anio, mes, 1)


def _decimal(valor: object) -> Decimal | None:
    if valor is None or str(valor).strip() == "":
        return None
    if isinstance(valor, Decimal | int | str):
        return Decimal(str(valor).strip())
    # Número binario de la planilla: se toma su representación decimal más corta.
    return Decimal(repr(valor))


def leer_cuadro(ruta: Path) -> tuple[list[Tramo], dict[str, date], list[Redondeo]]:
    """Tramos por concepto (valores iguales seguidos se unen), vencimientos por período y los
    valores que la planilla trae con decimales de una cuenta (1.745.699,9999…): se redondean al
    centavo y se informan, nunca en silencio."""
    libro = load_workbook(ruta, read_only=True, data_only=True)
    try:
        filas = [list(f) for f in libro["cuadro historico"].iter_rows(values_only=True)]
    finally:
        libro.close()
    rotulos: list[tuple[str, list[object]]] = [
        (_normal(f[2]) if len(f) > 2 else "", list(f)) for f in filas
    ]

    def una_fila(prefijo: str) -> list[object]:
        """La única fila cuyo rótulo empieza así: ninguna o varias es un cuadro inválido."""
        halladas = [f for r, f in rotulos if r.startswith(prefijo)]
        if len(halladas) != 1:
            raise CuadroInvalidoError(f"Se esperaba una fila «{prefijo}» y hay {len(halladas)}.")
        return halladas[0]

    periodos_fila, vencimientos_fila = una_fila("PERIODO"), una_fila("FECHA DE VENCIMIENTO")
    columnas: list[tuple[int, date, date]] = []
    for i in range(3, len(periodos_fila)):
        rotulo, vence = (
            periodos_fila[i],
            vencimientos_fila[i] if i < len(vencimientos_fila) else None,
        )
        if rotulo is None or not isinstance(vence, datetime | date):
            continue
        vence = vence.date() if isinstance(vence, datetime) else vence
        columnas.append((i, _periodo(rotulo, vence), vence))
    columnas.sort(key=lambda c: c[1])
    if len({c[1] for c in columnas}) != len(columnas):
        raise CuadroInvalidoError("Hay períodos repetidos en el cuadro.")

    por_concepto: dict[str, dict[date, dict[str, Decimal | None]]] = {}
    redondeos: list[Redondeo] = []
    for prefijo, codigo, campo in FILAS:
        fila = una_fila(prefijo)
        visto = False
        for i, periodo, _ in columnas:
            celda = fila[i] if i < len(fila) else None
            if campo == "monto_maximo" and _normal(celda) == SIN_TOPE:
                valor = None
            else:
                valor = _decimal(celda)
                if valor is None:
                    if visto:
                        # Una celda vacía después de haber valores no es «sin tope»: falta el dato.
                        raise CuadroInvalidoError(f"Falta {campo} de {codigo} en {periodo:%m/%Y}.")
                    continue  # el concepto todavía no existía (p. ej. médico asistencial en 2020)
                if campo == "porcentaje":
                    valor = valor * 100
                exacto = valor.quantize(
                    DIEZMILESIMO if campo == "porcentaje" else CENTAVO, ROUND_HALF_UP
                )
                if exacto != valor:
                    redondeos.append(Redondeo(codigo, periodo, campo, valor, exacto))
                valor = exacto
            visto = True
            por_concepto.setdefault(codigo, {}).setdefault(periodo, {})[campo] = valor

    tramos: list[Tramo] = []
    for codigo, periodos in por_concepto.items():
        abiertos: list[tuple[date, dict[str, Decimal | None]]] = []
        for periodo in sorted(periodos):
            valores = periodos[periodo]
            if not abiertos or abiertos[-1][1] != valores:
                abiertos.append((periodo, valores))
        for n, (desde, valores) in enumerate(abiertos):
            hasta = abiertos[n + 1][0] - timedelta(days=1) if n + 1 < len(abiertos) else None
            tramos.append(Tramo(codigo, desde, hasta, valores))
    vencimientos = {f"{p.year:04d}-{p.month:02d}": v for _, p, v in columnas}
    return tramos, vencimientos, redondeos


def anteriores_a(tramos: list[Tramo], inicio_existente: dict[str, date]) -> list[Tramo]:
    """Sólo lo anterior a la primera vigencia que ya tiene cada concepto (el último tramo se cierra
    el día antes). Un concepto que no está en el sistema no se crea acá."""
    resultado = []
    for t in tramos:
        inicio = inicio_existente.get(t.codigo)
        if inicio is None or t.desde >= inicio:
            continue
        hasta = t.hasta if t.hasta is not None and t.hasta < inicio else inicio - timedelta(days=1)
        resultado.append(Tramo(t.codigo, t.desde, hasta, t.valores))
    return resultado


async def cargar(
    session: AsyncSession, ruta: Path, propone: str, aprueba: str | None, simular: bool
) -> list[str]:
    from app.modules.ddjj.models import Vencimiento
    from app.modules.iam.models import User
    from app.modules.parametros import service
    from app.modules.parametros.models import Concepto, Vigencia

    tramos, vencimientos, redondeos = leer_cuadro(ruta)
    conceptos = {c.codigo: c for c in (await session.scalars(select(Concepto))).all()}
    inicio: dict[str, date] = {}
    for codigo, concepto in conceptos.items():
        primera = await session.scalar(
            select(Vigencia.fecha_desde)
            .where(
                Vigencia.concepto_id == concepto.id,
                Vigencia.estado.in_(("VIGENTE", "PENDIENTE_APROBACION")),
            )
            .order_by(Vigencia.fecha_desde)
            .limit(1)
        )
        if primera is not None:
            inicio[codigo] = primera
    a_cargar = anteriores_a(tramos, inicio)
    faltan = sorted(
        set(vencimientos) - set((await session.scalars(select(Vencimiento.periodo))).all())
    )
    informe = [f"{t.codigo} {t.desde} → {t.hasta or 'abierto'} {t.valores}" for t in a_cargar]
    informe.append(f"Vencimientos a completar: {len(faltan)} períodos.")
    informe += [
        f"Redondeado: {r.codigo} {r.periodo:%Y-%m} {r.campo} {r.original} → {r.redondeado}"
        for r in redondeos
    ]
    if simular:
        return informe

    actor = await session.scalar(select(User).where(User.email == propone))
    aprobador = await session.scalar(select(User).where(User.email == aprueba)) if aprueba else None
    if actor is None or (aprueba and aprobador is None):
        raise CuadroInvalidoError("No existe el usuario que propone o el que aprueba.")
    for t in a_cargar:
        datos = VigenciaIn(
            fecha_desde=t.desde,
            fecha_hasta=t.hasta,
            resolucion_respaldo=RESPALDO,
            motivo=MOTIVO,
            **{k: v for k, v in t.valores.items() if v is not None},
        )
        vigencia = await service.proponer_vigencia(
            session, CONTEXTO, actor, conceptos[t.codigo].id, datos
        )
        if aprobador is not None:
            await service.aprobar_vigencia(session, CONTEXTO, aprobador, vigencia.id)
    from app.modules.ddjj import service as ddjj

    # Por el servicio de DDJJ: valida que caiga después del período y lo audita.
    for periodo in faltan:
        await ddjj.fijar_vencimiento(session, CONTEXTO, actor, periodo, vencimientos[periodo])
    await session.commit()
    return informe


def main(argumentos: list[str] | None = None) -> int:
    lector = argparse.ArgumentParser(description="Carga los valores históricos de los aportes.")
    lector.add_argument("--planilla", type=Path, required=True)
    lector.add_argument("--propone", required=True)
    lector.add_argument("--aprueba")
    lector.add_argument("--simular", action="store_true")
    args = lector.parse_args(argumentos)

    async def correr() -> list[str]:
        from app.core.db import get_engine, get_sessionmaker

        try:
            async with get_sessionmaker()() as session:
                return await cargar(
                    session, args.planilla, args.propone, args.aprueba, args.simular
                )
        finally:
            await get_engine().dispose()

    try:
        lineas = asyncio.run(correr())
    except CuadroInvalidoError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write("\n".join(lineas) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
