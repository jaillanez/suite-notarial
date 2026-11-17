"""Comisiones del botón de pagos Supervielle, como parámetros que administra la Caja.

El banco cobra un porcentaje por el botón sobre todo lo cobrado, más uno según el medio con que
se paga. La API no informa la comisión de cada pago, así que la Suite la estima con los
parámetros vigentes a la fecha del pago (conceptos COMISION_COBRO del motor paramétrico). Si el
banco cambia un valor, la Caja carga una vigencia nueva desde Parámetros (con la aprobación de
una segunda persona); el código no cambia. Cada pago guarda las vigencias con que se estimó
(regla SNAP): un cambio posterior no altera las estimaciones ya hechas.

La comisión la absorbe la Caja: al escribano se le cobra el total exacto de la boleta.
TODO(negocio): confirmar con la Caja, como se definió para Mercado Pago el 27/10/2026.
TODO(banco): confirmar si los porcentajes incluyen IVA.

`proponer` carga los conceptos (si faltan) y propone los valores de la propuesta comercial del
banco; quedan pendientes hasta que otra persona con permiso de aprobación los apruebe:

python -m app.modules.pagos.comisiones_spv proponer --operador EMAIL --desde AAAA-MM-DD
"""

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import RequestContext
from app.core.errors import ProblemError
from app.modules.parametros import motor
from app.modules.parametros import service as parametros
from app.modules.parametros.catalog import TipoConcepto
from app.modules.parametros.models import Concepto
from app.modules.parametros.schemas import ConceptoIn, VigenciaIn

BOTON = "COMISION_SPV_BOTON"
# `id_medio_pago` de la API -> concepto de la comisión de ese medio. La API no distingue la
# marca de la tarjeta: un pago con crédito se estima con la tasa general (la de AMEX se usará
# cuando la rendición de transacciones informe la tarjeta).
POR_MEDIO: dict[int, str] = {
    1: "COMISION_SPV_CREDITO",
    2: "COMISION_SPV_DEBITO",
    3: "COMISION_SPV_EFECTIVO",
    4: "COMISION_SPV_MODO",
    5: "COMISION_SPV_DEBIN",
}


@dataclass(frozen=True)
class Propuesta:
    codigo: str
    nombre: str
    porcentaje: Decimal
    minimo: Decimal | None = None


# Propuesta comercial del banco («Botón de Pago | Pricing»). Los aranceles de tarjetas pueden
# cambiar por decisión de las marcas: se actualizan con una vigencia nueva.
PROPUESTA_BANCO: tuple[Propuesta, ...] = (
    Propuesta(BOTON, "Supervielle: botón de pago (sobre todo lo cobrado)", Decimal("0.4")),
    Propuesta(
        "COMISION_SPV_EFECTIVO",
        "Supervielle: pago en efectivo en cajas del banco",
        Decimal("0.25"),
        Decimal("500.00"),
    ),
    Propuesta("COMISION_SPV_DEBITO", "Supervielle: tarjeta de débito", Decimal("2")),
    Propuesta("COMISION_SPV_CREDITO", "Supervielle: tarjeta de crédito", Decimal("3")),
    Propuesta("COMISION_SPV_CREDITO_AMEX", "Supervielle: tarjeta de crédito AMEX", Decimal("2.8")),
    Propuesta("COMISION_SPV_MODO", "Supervielle: QR MODO", Decimal("0.8")),
    Propuesta("COMISION_SPV_DEBIN", "Supervielle: DEBIN", Decimal("0.1")),
)
RESPALDO = "Propuesta Supervielle Botón de Pago (Pricing)"
CLI_CONTEXT = RequestContext(
    ip_address=None, user_agent="cli", correlation_id=None, path="cli:pagos:comisiones_spv"
)


@dataclass(frozen=True)
class Estimacion:
    comision: Decimal
    vigencia_boton_id: uuid.UUID
    vigencia_medio_id: uuid.UUID


async def estimar(
    session: AsyncSession, importe: Decimal, id_medio: int | None, fecha: date
) -> Estimacion | None:
    """Comisión estimada de un pago: la del botón más la del medio, con las vigencias aprobadas
    a la fecha del pago. None si falta alguna (Tesorería ve «sin estimar»)."""
    codigo_medio = POR_MEDIO.get(id_medio) if id_medio is not None else None
    if codigo_medio is None:
        return None
    boton = await parametros.vigencia_opcional(session, BOTON, fecha)
    medio = await parametros.vigencia_opcional(session, codigo_medio, fecha)
    if boton is None or medio is None:
        return None
    if boton.tipo != TipoConcepto.COMISION_COBRO or medio.tipo != TipoConcepto.COMISION_COBRO:
        return None
    return Estimacion(
        comision=motor.comision_cobro(importe, boton) + motor.comision_cobro(importe, medio),
        vigencia_boton_id=boton.vigencia_id,
        vigencia_medio_id=medio.vigencia_id,
    )


async def proponer(session: AsyncSession, operador_email: str, desde: date) -> list[str]:
    """Crea los conceptos que falten y propone los valores del banco. Devuelve lo hecho."""
    from app.modules.iam.catalog import Perm
    from app.modules.iam.models import User

    operador = await session.scalar(
        select(User).where(User.email == operador_email.strip().lower())
    )
    if operador is None or not operador.is_active:
        raise ValueError(f"No hay un usuario activo con el correo {operador_email}.")
    if Perm.PARAMETERS_WRITE.value not in operador.permission_codes:
        raise ValueError("El operador no tiene permiso para proponer parámetros.")
    hecho: list[str] = []
    for p in PROPUESTA_BANCO:
        concepto = await session.scalar(select(Concepto).where(Concepto.codigo == p.codigo))
        if concepto is None:
            concepto = await parametros.create_concepto(
                session,
                CLI_CONTEXT,
                operador,
                ConceptoIn(
                    codigo=p.codigo,
                    nombre=p.nombre,
                    tipo=TipoConcepto.COMISION_COBRO,
                    descripcion="Comisión del botón de pagos Supervielle, en % de lo cobrado.",
                ),
            )
        if await parametros.list_vigencias(session, concepto.id):
            hecho.append(f"{p.codigo}: ya tiene valores cargados, no se toca")
            continue
        await parametros.proponer_vigencia(
            session,
            CLI_CONTEXT,
            operador,
            concepto.id,
            VigenciaIn(
                fecha_desde=desde,
                porcentaje=p.porcentaje,
                monto_minimo=p.minimo,
                resolucion_respaldo=RESPALDO,
                motivo="Valores de la propuesta comercial del banco para el botón de pagos.",
            ),
        )
        minimo = f", mínimo ${p.minimo}" if p.minimo is not None else ""
        hecho.append(f"{p.codigo}: propuesto {p.porcentaje} %{minimo} (pendiente de aprobación)")
    return hecho


async def _proponer_cli(operador: str, desde: date) -> int:
    from app.core.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        for linea in await proponer(session, operador, desde):
            sys.stdout.write(f"{linea}\n")
    return 0


def main(argumentos: list[str] | None = None) -> int:
    lector = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = lector.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("proponer", help="Propone los valores del banco (quedan a aprobar)")
    p.add_argument("--operador", required=True, help="Correo de un usuario que propone parámetros")
    p.add_argument("--desde", type=date.fromisoformat, required=True)
    args = lector.parse_args(argumentos)
    # Registra todos los modelos: corriendo solo, SQLAlchemy no resolvería las relaciones.
    import app.db.models  # noqa: F401

    try:
        return asyncio.run(_proponer_cli(args.operador, args.desde))
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except ProblemError as exc:
        sys.stderr.write(f"{exc.detail}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
