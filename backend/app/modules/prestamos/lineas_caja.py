"""Líneas de crédito vigentes de la Caja: Resolución N° 273, desde el 04/06/2026.

Fuente: planilla «Resumen Lineas de Credito.xlsx» de la Caja (hoja 1, «DESDE 04-06-2026 SEGÚN
RESOLUCION NRO 273»). Los valores se transcriben tal cual:

- «Tasa» es la tasa nominal anual (0,30 = 30 %); la cuota de la planilla es la del sistema
  francés con tasa mensual TNA / 12, y el motor la reproduce al centavo (ver tests).
- «Relación cuota/ingreso» 0,30 = tope de afectación del 30 % del ingreso neto.
- «Ingreso» de la planilla = cuota / 0,30: el ingreso mínimo para el monto y plazo máximos.

La planilla no fija monto ni plazo mínimos: van en el menor valor que admite el modelo.
TODO(negocio): confirmar con la Caja el monto mínimo y el plazo mínimo de cada línea.
TODO(negocio): definir qué implica que una línea sea «rotativa» (renovación del cupo).
TODO(negocio): criterio de «conducta regular en el último año» (hoy es informativo).
TODO(negocio): definir tipo de cambio para evaluar la afectación de préstamos en dólares.

Carga (idempotente, por código; nunca borra):

    python -m app.modules.prestamos.lineas_caja --operador EMAIL [--simular]

Crea las líneas que faltan, actualiza las que difieren de la resolución y deshabilita las líneas
de ejemplo que sigan habilitadas. Cada cambio queda en la auditoría a nombre del operador.
"""

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.core.db import get_engine, get_sessionmaker
from app.modules.iam.catalog import Perm
from app.modules.iam.models import User
from app.modules.prestamos.catalog import Moneda, Sistema
from app.modules.prestamos.models import Linea, Prestamo
from app.modules.prestamos.schemas import LineaIn
from app.modules.prestamos.service import LINEA_CAMPOS, columnas_linea, valores_linea

CONSOLA = RequestContext(
    ip_address=None, user_agent="cli", correlation_id=None, path="cli:prestamos.lineas_caja"
)
RESOLUCION = "Resolución N° 273, vigente desde el 04/06/2026."
CONDUCTA = "Conducta regular en el último año."
SOLA_FIRMA = "Sola firma."
SOLA_FIRMA_TERCERO = "Sola firma, más garantía de un tercero si es necesaria."
HIPOTECA = "Hipoteca."
AVISO_USD = (
    " Montos y cuotas en dólares estadounidenses. TODO(negocio): definir tipo de cambio para "
    "evaluar la afectación de préstamos en dólares; mientras tanto el ingreso neto se declara "
    "en dólares."
)
# TODO(negocio): monto y plazo mínimos no fijados por la Caja: el menor valor que admite el modelo.
MONTO_MINIMO = Decimal("0.01")
PLAZO_MINIMO = 1
UN_ANIO = 12


def _linea(
    codigo: str,
    nombre: str,
    *,
    monto_maximo: str,
    plazo_maximo: int,
    tna: str,
    garantia: str,
    certificados: bool,
    antiguedad_meses: int | None,
    conducta: str | None = CONDUCTA,
    relacion_capital_hipoteca: str | None = None,
    moneda: Moneda = Moneda.ARS,
) -> LineaIn:
    return LineaIn(
        codigo=codigo,
        nombre=nombre,
        descripcion=RESOLUCION + (AVISO_USD if moneda is Moneda.USD else ""),
        sistema=Sistema.FRANCES,
        plazo_minimo=PLAZO_MINIMO,
        plazo_maximo=plazo_maximo,
        monto_minimo=MONTO_MINIMO,
        monto_maximo=Decimal(monto_maximo),
        tna=Decimal(tna),
        afectacion_maxima=Decimal("30"),
        # «Garantía de un tercero si es necesaria»: la decide la Caja en cada caso, no la exige
        # la línea siempre.
        requiere_garante=False,
        moneda=moneda,
        garantia=garantia,
        requisito_conducta=conducta,
        relacion_capital_hipoteca=(
            Decimal(relacion_capital_hipoteca) if relacion_capital_hipoteca else None
        ),
        requiere_certificado_ingresos=certificados,
        requiere_certificado_bienes=certificados,
        antiguedad_minima_meses=antiguedad_meses,
        es_ejemplo=False,
        is_active=True,
    )


# Celdas B6:O13 de la planilla, en el mismo orden.
LINEAS_CAJA: tuple[LineaIn, ...] = (
    _linea(
        "PERSONAL_RAPIDO",
        "Personal rápido",
        monto_maximo="5000000",
        plazo_maximo=96,
        tna="30",
        garantia=SOLA_FIRMA,
        certificados=False,
        antiguedad_meses=UN_ANIO,
    ),
    _linea(
        "PERSONAL",
        "Personal",
        monto_maximo="10000000",
        plazo_maximo=96,
        tna="30",
        garantia=SOLA_FIRMA_TERCERO,
        certificados=True,
        antiguedad_meses=UN_ANIO,
    ),
    _linea(
        "PERSONAL_ROTATIVO",
        "Personal rotativo",
        monto_maximo="10000000",
        plazo_maximo=96,
        tna="34",
        garantia=SOLA_FIRMA_TERCERO,
        certificados=True,
        antiguedad_meses=UN_ANIO,
    ),
    _linea(
        "HIPOTECARIO",
        "Hipotecario",
        monto_maximo="30000000",
        plazo_maximo=180,
        tna="30",
        garantia=HIPOTECA,
        certificados=True,
        antiguedad_meses=UN_ANIO,
        relacion_capital_hipoteca="70",
    ),
    _linea(
        "HIPOTECARIO_ROTATIVO",
        "Hipotecario rotativo",
        monto_maximo="30000000",
        plazo_maximo=180,
        tna="34",
        garantia=HIPOTECA,
        certificados=True,
        antiguedad_meses=UN_ANIO,
        relacion_capital_hipoteca="70",
    ),
    _linea(
        "PASIVOS",
        "Pasivos",
        monto_maximo="3000000",
        plazo_maximo=36,
        tna="30",
        garantia=SOLA_FIRMA_TERCERO,
        certificados=False,
        # La planilla dice «NA» en antigüedad y no fija requisito de conducta.
        antiguedad_meses=None,
        conducta=None,
    ),
    _linea(
        "HIPOTECARIO_USD",
        "Hipotecario en dólares",
        monto_maximo="50000",
        plazo_maximo=60,
        tna="7",
        garantia=HIPOTECA,
        certificados=True,
        antiguedad_meses=UN_ANIO,
        relacion_capital_hipoteca="70",
        moneda=Moneda.USD,
    ),
    _linea(
        "HIPOTECARIO_ROTATIVO_USD",
        "Hipotecario rotativo en dólares",
        monto_maximo="50000",
        plazo_maximo=60,
        tna="8",
        garantia=HIPOTECA,
        certificados=True,
        antiguedad_meses=UN_ANIO,
        relacion_capital_hipoteca="70",
        moneda=Moneda.USD,
    ),
)

# Columnas I (cuota) y J (ingreso) de la planilla, con los decimales que muestra: sirven para
# verificar que el motor reproduce la cuota de la Caja al centavo.
PLANILLA_CUOTA_INGRESO: dict[str, tuple[str, str]] = {
    "PERSONAL_RAPIDO": ("137883.086373", "459610.28791"),
    "PERSONAL": ("275766.172746", "919220.575821"),
    "PERSONAL_ROTATIVO": ("304140.787967", "1013802.626556"),
    "HIPOTECARIO": ("758910.34879", "2529701.162633"),
    "HIPOTECARIO_ROTATIVO": ("855599.718249", "2851999.060831"),
    "PASIVOS": ("127354.73023", "424515.767435"),
    "HIPOTECARIO_USD": ("990.059927", "3300.199757"),
    "HIPOTECARIO_ROTATIVO_USD": ("1013.819714", "3379.399048"),
}


class LineasCajaError(Exception):
    """La carga no se puede hacer (operador, moneda): mensaje para la consola."""


@dataclass
class Resumen:
    creadas: list[str] = field(default_factory=list)
    actualizadas: list[str] = field(default_factory=list)
    sin_cambios: list[str] = field(default_factory=list)
    deshabilitadas: list[str] = field(default_factory=list)


async def operador(session: AsyncSession, email: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        raise LineasCajaError(f"No hay un usuario activo con el correo {email}.")
    if Perm.PRESTAMOS_MANAGE.value not in user.permission_codes:
        raise LineasCajaError("El operador no tiene el permiso prestamos:manage.")
    return user


async def cargar(session: AsyncSession, actor: User) -> Resumen:
    """Deja las líneas como en la resolución. No confirma: lo hace quien llama."""
    resumen = Resumen()
    codigos = {x.codigo for x in LINEAS_CAJA}
    for data in LINEAS_CAJA:
        valores = columnas_linea(data)
        linea = await session.scalar(
            select(Linea).where(Linea.codigo == data.codigo).with_for_update()
        )
        if linea is None:
            linea = Linea(id=uuid.uuid4(), **valores, created_by_user_id=actor.id)
            session.add(linea)
            record_audit(
                session,
                CONSOLA,
                AuditEvent.PRESTAMO_LINEA_CREADA,
                severity=Severity.WARNING,
                actor_user_id=actor.id,
                new_value=valores_linea(linea),
                details={"linea_id": str(linea.id), "origen": RESOLUCION},
            )
            resumen.creadas.append(data.codigo)
            continue
        antes = valores_linea(linea)
        if data.moneda.value != linea.moneda and await session.scalar(
            select(Prestamo.id).where(Prestamo.linea_id == linea.id).limit(1)
        ):
            raise LineasCajaError(
                f"La línea {data.codigo} ya tiene préstamos en {linea.moneda}: su moneda no "
                "cambia. Revisala antes de cargar la resolución."
            )
        for campo, valor in valores.items():
            setattr(linea, campo, valor)
        despues = valores_linea(linea)
        cambios = [c for c in LINEA_CAMPOS if antes[c] != despues[c]]
        if not cambios:
            resumen.sin_cambios.append(data.codigo)
            continue
        record_audit(
            session,
            CONSOLA,
            AuditEvent.PRESTAMO_LINEA_ACTUALIZADA,
            severity=Severity.WARNING,
            actor_user_id=actor.id,
            old_value={c: antes[c] for c in cambios},
            new_value={c: despues[c] for c in cambios},
            details={"linea_id": str(linea.id), "codigo": linea.codigo, "origen": RESOLUCION},
        )
        resumen.actualizadas.append(data.codigo)

    ejemplos = await session.scalars(
        select(Linea)
        .where(
            Linea.es_ejemplo.is_(True),
            Linea.is_active.is_(True),
            Linea.codigo.not_in(codigos),
        )
        .order_by(Linea.codigo)
        .with_for_update()
    )
    for linea in ejemplos.all():
        # Baja lógica: los préstamos ya pedidos conservan sus condiciones (SNAP).
        linea.is_active = False
        record_audit(
            session,
            CONSOLA,
            AuditEvent.PRESTAMO_LINEA_ACTUALIZADA,
            severity=Severity.WARNING,
            actor_user_id=actor.id,
            old_value={"is_active": True},
            new_value={"is_active": False},
            details={
                "linea_id": str(linea.id),
                "codigo": linea.codigo,
                "motivo": f"Línea de ejemplo reemplazada por las de la {RESOLUCION}",
            },
        )
        resumen.deshabilitadas.append(linea.codigo)
    await session.flush()
    return resumen


def _out(mensaje: str) -> None:
    sys.stdout.write(mensaje + "\n")


def _err(mensaje: str) -> None:
    sys.stderr.write(mensaje + "\n")


def _informar(resumen: Resumen, *, simular: bool) -> None:
    _out(("SIMULACIÓN (no se guardó nada) · " if simular else "") + RESOLUCION)
    for titulo, codigos in (
        ("Creadas", resumen.creadas),
        ("Actualizadas", resumen.actualizadas),
        ("Sin cambios", resumen.sin_cambios),
        ("Líneas de ejemplo deshabilitadas", resumen.deshabilitadas),
    ):
        _out(f"{titulo}: {len(codigos)}" + (f" ({', '.join(codigos)})" if codigos else ""))


async def ejecutar(email: str, *, simular: bool) -> Resumen:
    async with get_sessionmaker()() as session:
        actor = await operador(session, email)
        resumen = await cargar(session, actor)
        if simular:
            await session.rollback()
        else:
            await session.commit()
        return resumen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lineas_caja", description=f"Carga las líneas de crédito de la {RESOLUCION}"
    )
    parser.add_argument(
        "--operador", required=True, help="Correo de un usuario con prestamos:manage"
    )
    parser.add_argument(
        "--simular", action="store_true", help="Muestra qué cambiaría, sin guardar nada"
    )
    args = parser.parse_args(argv)

    async def correr() -> int:
        try:
            resumen = await ejecutar(args.operador, simular=args.simular)
        except LineasCajaError as exc:
            _err(str(exc))
            return 2
        finally:
            await get_engine().dispose()
        _informar(resumen, simular=args.simular)
        return 0

    return asyncio.run(correr())


if __name__ == "__main__":
    raise SystemExit(main())
