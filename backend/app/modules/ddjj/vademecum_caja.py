"""Vademécum de aportes 2026 de la Caja, transcripto del documento «VADEMECUM 2026 11.docx».

«Aportes Caja Notarial (conforme lo resuelto en la Asamblea Extraordinaria del 19/05/2026).
Vigencia: a partir de junio 2026.» Los montos (0,40 % con mínimo y máximo; fijos mayores y
menores) no se cargan acá: ya son las vigencias de junio 2026 del motor paramétrico, y coinciden
al centavo con el documento.

Donde el documento hace depender el aporte de una condición, se cargan dos actos (cesión onerosa
sobre inmueble determinado y las demás cesiones; actos del IPV exentos y los demás; actas
laborales, subsanatorias y de regulación dominial aparte de las demás actas), así el escribano
elige uno y nunca la categoría. Algunas letras del documento original están en alfabeto cirílico
(la «A» de «VENTA» y de «ACTA», entre otras): acá se transcriben en latino para que el buscador
las encuentre.

Además propone el criterio de pluralidad del documento («cuando en una escritura hay más de un
acto y solo dos partes, solo corresponde aportar por uno de ellos, el de mayor valor») como
vigencia desde junio 2026, pendiente de aprobación por otra persona, como cualquier parámetro.
«El de mayor valor» se toma como el acto que más aporta. TODO(negocio): confirmarlo con la Caja.

Carga (idempotente por código: no toca los actos que ya están):

    python -m app.modules.ddjj.vademecum_caja --operador EMAIL [--simular]
"""

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Registra todos los modelos: corriendo solo, SQLAlchemy no resolvería las relaciones.
import app.db.models  # noqa: F401
from app.common.audit import RequestContext
from app.core.db import get_engine, get_sessionmaker
from app.modules.ddjj import vademecum
from app.modules.ddjj.catalog import CONCEPTO_PLURALIDAD, CategoriaActo, MotivoExencion
from app.modules.ddjj.models import VademecumActo
from app.modules.ddjj.schemas import VademecumIn
from app.modules.iam.catalog import Perm
from app.modules.iam.models import User
from app.modules.parametros import service as parametros
from app.modules.parametros.catalog import CriterioPluralidad, EstadoVigencia, TipoConcepto
from app.modules.parametros.models import Concepto, Vigencia
from app.modules.parametros.schemas import ConceptoIn, VigenciaIn

CONSOLA = RequestContext(
    ip_address=None, user_agent="cli", correlation_id=None, path="cli:ddjj.vademecum_caja"
)
DESDE = date(2026, 6, 1)
RESOLUCION = "Vademécum de aportes · Asamblea Extraordinaria del 19/05/2026"
MOTIVO = "Carga del vademécum de aportes vigente desde junio 2026."

V = CategoriaActo.ESCRITURA_CON_VALOR
MAYOR = CategoriaActo.OTRO_ACTO
MENOR = CategoriaActo.ACTA_O_PODER
EXENTO = CategoriaActo.EXENTO
SIN_IPV = "Excepto las del IPV, que están exentas."


@dataclass(frozen=True)
class ActoVademecum:
    codigo: str
    nombre: str
    categoria: CategoriaActo
    motivo_exencion: MotivoExencion | None = None
    aclaracion: str | None = None
    sinonimos: str | None = None


# En el orden del documento: I) variable, II) fijos mayores, III) fijos menores, IV) exentos.
GRUPOS: tuple[tuple[ActoVademecum, ...], ...] = (
    (
        ActoVademecum("VENTA", "Venta", V, sinonimos="compraventa"),
        ActoVademecum(
            "CESION_ONEROSA_INMUEBLE",
            "Cesión onerosa sobre inmueble determinado",
            V,
            aclaracion="Solo cuando es onerosa y sobre un inmueble determinado. Las demás "
            "cesiones son aporte fijo mayor.",
            sinonimos="cesión de derechos, cesión onerosa",
        ),
        ActoVademecum("DACION_EN_PAGO", "Dación en pago", V),
        ActoVademecum(
            "HIPOTECA",
            "Hipoteca o mutuo hipotecario",
            V,
            aclaracion=SIN_IPV,
            sinonimos="mutuo hipotecario",
        ),
        ActoVademecum("PERMUTA", "Permuta", V),
    ),
    (
        ActoVademecum(
            "DONACION",
            "Donación - aceptación de compra y/o venta",
            MAYOR,
            sinonimos="aceptación de donación, aceptación de compra, aceptación de venta",
        ),
        ActoVademecum(
            "CESION",
            "Cesión",
            MAYOR,
            aclaracion="Las cesiones onerosas sobre un inmueble determinado son aporte variable.",
            sinonimos="cesión de derechos, cesión gratuita",
        ),
        ActoVademecum("SUBDIVISION", "Subdivisión o división parcelaria", MAYOR),
        ActoVademecum("INTEGRACION_PARCELARIA", "Integración parcelaria", MAYOR),
        ActoVademecum(
            "PROPIEDAD_HORIZONTAL",
            "Sometimiento a PH o reglamento de copropiedad",
            MAYOR,
            sinonimos="propiedad horizontal, reglamento de copropiedad",
        ),
        ActoVademecum(
            "USUFRUCTO", "Constitución o renuncia de usufructo", MAYOR, sinonimos="usufructo"
        ),
        ActoVademecum("SERVIDUMBRE", "Constitución de servidumbre", MAYOR),
        ActoVademecum("FIDEICOMISO", "Fideicomiso", MAYOR),
        ActoVademecum(
            "MODIFICACION_CONTRATO_SOCIAL",
            "Modificación de contrato social",
            MAYOR,
            sinonimos="sociedad, estatuto",
        ),
        ActoVademecum("CONSTITUCION_SOCIEDAD", "Constitución de sociedad", MAYOR),
        ActoVademecum("CONVENIOS", "Convenios", MAYOR, sinonimos="convenio"),
        ActoVademecum(
            "ACTA_LABORAL",
            "Acta de extinción de relación laboral (acta laboral)",
            MAYOR,
            sinonimos="acta laboral, despido, renuncia laboral",
        ),
        ActoVademecum("ADJUDICACION", "Adjudicación", MAYOR),
        ActoVademecum("DISTRACTO", "Distracto", MAYOR),
        ActoVademecum("DIVISION_CONDOMINIO", "División de condominio", MAYOR),
        ActoVademecum("TESTAMENTO", "Testamento", MAYOR),
    ),
    (
        ActoVademecum(
            "ACTA",
            "Acta",
            MENOR,
            aclaracion="Todas, excepto las subsanatorias y las de regulación dominial, que no "
            "aportan, y las laborales, que son aporte fijo mayor.",
            sinonimos="acta de constatación, acta de notificación, acta de comprobación",
        ),
        ActoVademecum("PODER", "Poder", MENOR, sinonimos="poder general, poder especial, mandato"),
        ActoVademecum("REVOCACION", "Revocación", MENOR, sinonimos="revocación de poder"),
        ActoVademecum("SUSTITUCION_PODER", "Sustitución de poder", MENOR),
        ActoVademecum(
            "AFECTACION_VIVIENDA",
            "Afectación al régimen de vivienda",
            MENOR,
            sinonimos="bien de familia, protección de la vivienda",
        ),
        ActoVademecum("CANCELACION_HIPOTECA", "Cancelación de hipoteca", MENOR, aclaracion=SIN_IPV),
        ActoVademecum(
            "CANCELACION_USUFRUCTO",
            "Cancelación de usufructo por fallecimiento",
            MENOR,
        ),
        ActoVademecum("CANCELACION_EMBARGO", "Cancelación de embargo", MENOR),
        ActoVademecum("PROTESTO", "Protesto", MENOR),
    ),
    (
        ActoVademecum(
            "ACTA_SUBSANATORIA",
            "Acta subsanatoria (rectificatoria)",
            EXENTO,
            MotivoExencion.ACTA_SUBSANATORIA,
            aclaracion="Exclusivamente las que son rectificatorias.",
            sinonimos="rectificatoria, subsanación",
        ),
        ActoVademecum(
            "IPV",
            "Hipoteca, cancelación de hipoteca, poder o venta del IPV",
            EXENTO,
            MotivoExencion.CONVENIO_IPV,
            aclaracion="Escrituras emanadas del Instituto Provincial de la Vivienda.",
            sinonimos="instituto provincial de la vivienda, IPV",
        ),
        ActoVademecum(
            "ASOCIACION_INTERMEDIA_IPV",
            "Asociación intermedia con hipoteca a favor del IPV",
            EXENTO,
            MotivoExencion.ASOCIACION_INTERMEDIA_IPV,
            sinonimos="asociación intermedia, IPV",
        ),
        ActoVademecum(
            "REGULACION_DOMINIAL",
            "Acta de regulación dominial",
            EXENTO,
            MotivoExencion.REGULACION_DOMINIAL,
            sinonimos="regularización dominial",
        ),
    ),
)

CONCEPTO = ConceptoIn(
    codigo=CONCEPTO_PLURALIDAD,
    nombre="Pluralidad de actos en una escritura",
    tipo=TipoConcepto.CRITERIO_PLURALIDAD,
    descripcion="Cómo aportan los actos de una escritura con varios actos y las mismas partes. "
    "Con partes distintas aporta cada acto.",
)
CRITERIO = VigenciaIn(
    fecha_desde=DESDE,
    criterio=CriterioPluralidad.SOLO_EL_MAYOR,
    resolucion_respaldo=RESOLUCION,
    motivo="Vademécum 2026, nota «pluralidad de actos»: con solo dos partes aporta únicamente "
    "el acto de mayor valor (se toma el que más aporta). TODO(negocio): confirmar con la Caja.",
)


class VademecumCajaError(Exception):
    """La carga no se puede hacer (operador): mensaje para la consola."""


@dataclass
class Resumen:
    creados: list[str] = field(default_factory=list)
    ya_cargados: list[str] = field(default_factory=list)
    criterio: str = ""
    # Vigencia del criterio propuesta en esta carga (queda pendiente de aprobación).
    propuesta_id: uuid.UUID | None = None


def actos() -> list[tuple[int, ActoVademecum]]:
    """Cada acto con su orden: centena por grupo del documento, unidad por posición."""
    return [
        ((g + 1) * 100 + i + 1, acto)
        for g, grupo in enumerate(GRUPOS)
        for i, acto in enumerate(grupo)
    ]


async def operador(session: AsyncSession, email: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        raise VademecumCajaError(f"No hay un usuario activo con el correo {email}.")
    if Perm.PARAMETERS_WRITE.value not in user.permission_codes:
        raise VademecumCajaError("El operador no tiene el permiso parameters:write.")
    return user


async def cargar_criterio(session: AsyncSession, actor: User) -> Vigencia | None:
    """Crea el concepto si falta y propone el criterio del documento si el concepto no tiene
    ninguna vigencia ni propuesta para junio 2026. Devuelve la propuesta nueva."""
    concepto = await session.scalar(select(Concepto).where(Concepto.codigo == CONCEPTO.codigo))
    if concepto is None:
        concepto = await parametros.create_concepto(session, CONSOLA, actor, CONCEPTO)
    existentes = await session.scalars(
        select(Vigencia).where(
            Vigencia.concepto_id == concepto.id,
            Vigencia.estado.in_(
                [EstadoVigencia.VIGENTE.value, EstadoVigencia.PENDIENTE_APROBACION.value]
            ),
        )
    )
    if existentes.first() is not None:
        return None
    return await parametros.proponer_vigencia(session, CONSOLA, actor, concepto.id, CRITERIO)


async def cargar(session: AsyncSession, actor: User) -> Resumen:
    """Carga los actos que falten y propone el criterio. Cada alta confirma por separado."""
    resumen = Resumen()
    for orden, acto in actos():
        existe = await session.scalar(
            select(VademecumActo.id).where(VademecumActo.codigo == acto.codigo).limit(1)
        )
        if existe is not None:
            resumen.ya_cargados.append(acto.codigo)
            continue
        await vademecum.agregar(
            session,
            CONSOLA,
            actor,
            VademecumIn(
                codigo=acto.codigo,
                nombre=acto.nombre,
                categoria=acto.categoria,
                motivo_exencion=acto.motivo_exencion,
                aclaracion=acto.aclaracion,
                sinonimos=acto.sinonimos,
                orden=orden,
                fecha_desde=DESDE,
                resolucion=RESOLUCION,
                motivo=MOTIVO,
            ),
        )
        resumen.creados.append(acto.codigo)
    propuesta = await cargar_criterio(session, actor)
    resumen.propuesta_id = propuesta.id if propuesta is not None else None
    resumen.criterio = (
        "propuesto (pendiente de aprobación por otra persona)"
        if propuesta is not None
        else "ya tenía vigencia o propuesta"
    )
    return resumen


def _out(mensaje: str) -> None:
    sys.stdout.write(mensaje + "\n")


def _err(mensaje: str) -> None:
    sys.stderr.write(mensaje + "\n")


async def ejecutar(email: str, *, simular: bool) -> Resumen:
    async with get_sessionmaker()() as session:
        actor = await operador(session, email)
        if simular:
            resumen = Resumen()
            for _, acto in actos():
                existe = await session.scalar(
                    select(VademecumActo.id).where(VademecumActo.codigo == acto.codigo).limit(1)
                )
                (resumen.ya_cargados if existe else resumen.creados).append(acto.codigo)
            resumen.criterio = "no se revisa en la simulación"
            return resumen
        return await cargar(session, actor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vademecum_caja", description=f"Carga el vademécum de aportes ({RESOLUCION})"
    )
    parser.add_argument(
        "--operador", required=True, help="Correo de un usuario con parameters:write"
    )
    parser.add_argument(
        "--simular", action="store_true", help="Muestra qué se cargaría, sin guardar nada"
    )
    args = parser.parse_args(argv)

    async def correr() -> int:
        try:
            resumen = await ejecutar(args.operador, simular=args.simular)
        except VademecumCajaError as exc:
            _err(str(exc))
            return 2
        finally:
            await get_engine().dispose()
        _out(("SIMULACIÓN (no se guardó nada) · " if args.simular else "") + RESOLUCION)
        _out(f"Actos creados: {len(resumen.creados)}")
        _out(f"Actos que ya estaban: {len(resumen.ya_cargados)}")
        _out(f"Criterio de pluralidad: {resumen.criterio}")
        return 0

    return asyncio.run(correr())


if __name__ == "__main__":
    raise SystemExit(main())
