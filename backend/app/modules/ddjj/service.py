"""Declaraciones juradas mensuales y boletas (Módulo 5).

Acceso por registro notarial:
- Un escribano opera las DDJJ de los registros donde tiene un cargo vigente (`ddjj:create_own`,
  que exige matrícula activa) y consulta las de los registros donde tuvo cargo (`ddjj:read_own`).
- El personal de la Caja consulta todo (`ddjj:read_all`) y puede cargar y presentar en nombre
  del registro (`ddjj:approve`), como hoy en el sistema actual.

El cálculo se hace siempre en el servidor (`liquidacion.liquidar_por_escribano`) con las
vigencias del primer día del período. La DDJJ es del registro, pero cada escribano del equipo
recibe su propia boleta y la paga en su fecha. Al presentar se congelan el aporte y la vigencia
de cada acto, y cada boleta guarda su escribano, su modalidad y las vigencias del mínimo, el
aporte médico y la mora (SNAP).
"""

import base64
import calendar
import hashlib
import json
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.dates import today_local
from app.common.money import to_money
from app.common.pagination import PageParams
from app.core.errors import ProblemError
from app.modules.ddjj import protocolo, vademecum
from app.modules.ddjj.catalog import (
    CONCEPTO_MEDICO,
    CONCEPTO_MINIMO,
    CONCEPTO_MORA,
    CONCEPTO_PLURALIDAD,
    CONCEPTO_POR_CATEGORIA,
    CategoriaActo,
    EstadoBoleta,
    EstadoDDJJ,
    ModalidadBoleta,
    TipoProtocolo,
)
from app.modules.ddjj.liquidacion import (
    ActoALiquidar,
    AporteActo,
    Liquidacion,
    LiquidacionError,
    LiquidacionEscribano,
    Obligado,
    aporte_de_acto,
    liquidar_por_escribano,
    totalizar,
)
from app.modules.ddjj.models import (
    Acto,
    Boleta,
    BoletaTramoMora,
    DeclaracionJurada,
    VademecumActo,
    Vencimiento,
)
from app.modules.ddjj.pdf import DatosBoleta, EscribanoBoleta
from app.modules.ddjj.schemas import (
    ActoIn,
    DeclaracionIn,
    PresentarIn,
    VerificacionActoIn,
    base_de,
)
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal
from app.modules.iam.models import User
from app.modules.padron import a_cargo
from app.modules.padron.catalog import AporteACargo, Cargo, EstadoRegistro
from app.modules.padron.models import Adscripcion, Escribano, RegistroNotarial
from app.modules.pagos.catalog import EstadoComprobante
from app.modules.pagos.models import Comprobante
from app.modules.parametros import service as parametros
from app.modules.parametros.models import Vigencia
from app.modules.parametros.motor import VigenciaSnapshot

# Plazo máximo entre la emisión de una boleta y la fecha hasta la que se puede pagar.
# TODO(negocio): confirmar con la Caja el plazo de validez de una boleta.
MAX_DIAS_VALIDEZ_BOLETA = 60
# Tope técnico de actos por DDJJ (acota el costo de liquidar y controlar una declaración).
MAX_ACTOS_POR_DDJJ = 2000
CARGO_TEXTO = {
    Cargo.TITULAR.value: "Titular",
    Cargo.ADSCRIPTO.value: "Adscripto",
    Cargo.SUPLENTE_INTERINO.value: "A cargo",
}
# Qué cobra la boleta de quien está a cargo, según lo que fijó la Caja en su designación. None:
# no tiene boleta propia, sus actos se cobran en la del titular.
MODALIDAD_A_CARGO: dict[str, ModalidadBoleta | None] = {
    AporteACargo.SOLO_ACTOS.value: ModalidadBoleta.SOLO_ACTOS,
    AporteACargo.CON_MINIMO.value: ModalidadBoleta.CON_MINIMO,
    AporteACargo.EN_BOLETA_DEL_TITULAR.value: None,
}


def _not_found(what: str) -> ProblemError:
    return ProblemError(HTTPStatus.NOT_FOUND, f"{what} no existe.")


def _conflict(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.CONFLICT, message)


def _invalid(message: str) -> ProblemError:
    return ProblemError(HTTPStatus.UNPROCESSABLE_ENTITY, message)


# --------------------------------------------------------------------------- períodos


def rango_periodo(periodo: str) -> tuple[date, date]:
    anio, mes = int(periodo[:4]), int(periodo[5:7])
    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


def periodo_de(fecha: date) -> str:
    return f"{fecha.year:04d}-{fecha.month:02d}"


def _texto_periodo(periodo: str) -> str:
    return f"{periodo[5:7]}/{periodo[:4]}"


# --------------------------------------------------------------------------- acceso


async def _escribano_de(session: AsyncSession, user: User) -> Escribano | None:
    return await session.scalar(select(Escribano).where(Escribano.user_id == user.id))


async def _registros_del_escribano(
    session: AsyncSession, user: User, *, solo_vigentes: bool
) -> set[uuid.UUID]:
    escribano = await _escribano_de(session, user)
    if escribano is None:
        return set()
    stmt = select(Adscripcion.registro_id).where(Adscripcion.escribano_id == escribano.id)
    if solo_vigentes:
        stmt = stmt.where(Adscripcion.is_current.is_(True))
    propios = set((await session.scalars(stmt)).all())
    # A cargo de otro registro: solo entre las fechas de la designación aprobada.
    designaciones = await a_cargo.del_escribano(
        session, escribano.id, en=today_local() if solo_vigentes else None
    )
    return propios | {d.registro_id for d in designaciones}


def _es_staff_lectura(principal: Principal) -> bool:
    return Perm.DDJJ_READ_ALL.value in principal.permissions


def _es_staff_carga(principal: Principal) -> bool:
    return Perm.DDJJ_APPROVE.value in principal.permissions


async def puede_reemitir(
    session: AsyncSession,
    principal: Principal,
    registro_id: uuid.UUID,
    escribano_id: uuid.UUID | None,
) -> bool:
    """Reemitir anula la boleta pendiente: cada escribano reemite solo la suya (las boletas son
    independientes) y la Caja, cualquiera. La boleta del registro (anterior a las boletas por
    notario) la reemite quien opera el registro, como antes."""
    if _es_staff_carga(principal):
        return True
    if not await puede_operar(session, principal, registro_id):
        return False
    if escribano_id is None:
        return True
    propio = await _escribano_de(session, principal.user)
    return propio is not None and propio.id == escribano_id


async def puede_operar(session: AsyncSession, principal: Principal, registro_id: uuid.UUID) -> bool:
    if _es_staff_carga(principal):
        return True
    if Perm.DDJJ_CREATE_OWN.value not in principal.permissions:
        return False
    return registro_id in await _registros_del_escribano(
        session, principal.user, solo_vigentes=True
    )


@dataclass(frozen=True)
class Alcance:
    """Registro y meses en que el escribano tuvo cargo: solo ve las DDJJ de ese tramo."""

    registro_id: uuid.UUID
    desde: str
    hasta: str | None

    def incluye(self, registro_id: uuid.UUID, periodo: str) -> bool:
        return (
            registro_id == self.registro_id
            and periodo >= self.desde
            and (self.hasta is None or periodo <= self.hasta)
        )

    def condicion(
        self,
        registro_col: InstrumentedAttribute[uuid.UUID],
        periodo_col: InstrumentedAttribute[str],
    ) -> ColumnElement[bool]:
        partes = [registro_col == self.registro_id, periodo_col >= self.desde]
        if self.hasta is not None:
            partes.append(periodo_col <= self.hasta)
        return and_(*partes)


def incluye(alcance: list[Alcance], registro_id: uuid.UUID, periodo: str) -> bool:
    return any(a.incluye(registro_id, periodo) for a in alcance)


async def _alcance_propio(session: AsyncSession, user: User) -> list[Alcance]:
    escribano = await _escribano_de(session, user)
    if escribano is None:
        return []
    cargos = await session.scalars(
        select(Adscripcion).where(Adscripcion.escribano_id == escribano.id)
    )
    designaciones = await a_cargo.del_escribano(session, escribano.id)
    return [
        Alcance(
            c.registro_id,
            periodo_de(c.inicio),
            periodo_de(c.fecha_hasta) if c.fecha_hasta else None,
        )
        for c in cargos.unique()
    ] + [
        Alcance(d.registro_id, periodo_de(d.fecha_desde), periodo_de(d.fecha_hasta))
        for d in designaciones
    ]


async def _alcance_lectura(
    session: AsyncSession, principal: Principal, *, todo: tuple[Perm, ...], propio: Perm
) -> list[Alcance] | None:
    """`None` significa todo; si no, los tramos de cargo propios (o ninguno)."""
    if any(p.value in principal.permissions for p in todo):
        return None
    if propio.value not in principal.permissions:
        return []
    return await _alcance_propio(session, principal.user)


async def _alcance_ddjj(session: AsyncSession, principal: Principal) -> list[Alcance] | None:
    return await _alcance_lectura(
        session, principal, todo=(Perm.DDJJ_READ_ALL, Perm.DDJJ_APPROVE), propio=Perm.DDJJ_READ_OWN
    )


async def _exigir_lectura(
    session: AsyncSession, principal: Principal, ddjj: DeclaracionJurada
) -> None:
    alcance = await _alcance_ddjj(session, principal)
    if alcance is not None and not any(a.incluye(ddjj.registro_id, ddjj.periodo) for a in alcance):
        # No se revela si la DDJJ existe en un registro ajeno.
        raise _not_found("La declaración jurada")


def ve_todo(principal: Principal) -> bool:
    """Personal de la Caja: puede ver quién de la Caja operó cada trámite."""
    return any(
        p.value in principal.permissions
        for p in (Perm.DDJJ_READ_ALL, Perm.DDJJ_APPROVE, Perm.BOLETAS_READ_ALL)
    )


async def _exigir_operacion(
    session: AsyncSession, principal: Principal, registro_id: uuid.UUID
) -> None:
    if not await puede_operar(session, principal, registro_id):
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "No tenés un cargo vigente en este registro para operar su declaración jurada.",
        )


# --------------------------------------------------------------------------- registros y cargos


async def registros_operables(
    session: AsyncSession, principal: Principal
) -> list[RegistroNotarial]:
    stmt = select(RegistroNotarial).where(RegistroNotarial.estado != EstadoRegistro.CERRADO.value)
    if not _es_staff_carga(principal):
        ids = (
            await _registros_del_escribano(session, principal.user, solo_vigentes=True)
            if Perm.DDJJ_CREATE_OWN.value in principal.permissions
            else set()
        )
        if not ids:
            return []
        stmt = stmt.where(RegistroNotarial.id.in_(ids))
    result = await session.execute(stmt.order_by(RegistroNotarial.numero_registro))
    return list(result.unique().scalars())


@dataclass(frozen=True)
class CargoEnPeriodo:
    """Lugar de un escribano en el equipo del registro durante un período: su cargo propio o
    una designación a cargo aprobada."""

    escribano: Escribano
    cargo: str
    fecha_desde: date
    fecha_hasta: date | None
    # Solo en las designaciones a cargo: qué paga por los actos (catalog.AporteACargo).
    aporte: str | None = None

    @property
    def escribano_id(self) -> uuid.UUID:
        return self.escribano.id


# Titular, adscriptos y, al final, quienes estuvieron a cargo.
_ORDEN_CARGO = {Cargo.TITULAR.value: 0, Cargo.ADSCRIPTO.value: 1}


async def cargos_en_periodo(
    session: AsyncSession, registro_id: uuid.UUID, periodo: str
) -> list[CargoEnPeriodo]:
    """Equipo del registro en algún día del período, incluidos los escribanos a cargo."""
    desde, hasta = rango_periodo(periodo)
    result = await session.execute(
        select(Adscripcion).where(
            Adscripcion.registro_id == registro_id,
            Adscripcion.empezo_hasta(hasta),
            or_(Adscripcion.fecha_hasta.is_(None), Adscripcion.fecha_hasta >= desde),
        )
    )
    cargos = [
        CargoEnPeriodo(c.escribano, c.cargo, c.inicio, c.fecha_hasta)
        for c in result.unique().scalars()
    ]
    cargos += [
        CargoEnPeriodo(
            d.escribano, Cargo.SUPLENTE_INTERINO.value, d.fecha_desde, d.fecha_hasta, d.aporte
        )
        for d in await a_cargo.aprobadas_en(session, registro_id, desde, hasta)
    ]
    return sorted(cargos, key=lambda c: (_ORDEN_CARGO.get(c.cargo, 2), c.fecha_desde))


def nombre_escribano(escribano: Escribano) -> str:
    persona = escribano.persona
    return f"{persona.apellido.upper()}, {persona.nombre}"


def obligados(cargos: list[CargoEnPeriodo]) -> list[Obligado]:
    """Quién recibe boleta por la DDJJ del registro y qué le cobra.

    Titular y adscripto: mínimo, médico y excedente (cada uno el suyo). Quien está a cargo: lo
    que fijó la Caja en la designación. Quien tuvo dos lugares en el período (p. ej. pasó de
    adscripto a titular) tiene una sola boleta, con el de mayor rango.
    """
    vistos: dict[uuid.UUID, Obligado] = {}
    for c in cargos:  # ordenados: titular, adscriptos y al final quienes estuvieron a cargo
        if c.escribano_id in vistos:
            continue
        modalidad = (
            MODALIDAD_A_CARGO[c.aporte or AporteACargo.SOLO_ACTOS.value]
            if c.cargo == Cargo.SUPLENTE_INTERINO.value
            else ModalidadBoleta.COMPLETA
        )
        vistos[c.escribano_id] = Obligado(c.escribano_id, c.cargo, modalidad)
    return list(vistos.values())


def avisos_de_minimo(
    cargos: list[CargoEnPeriodo], equipo: list[Obligado], periodo: str
) -> list[str]:
    """Quien empieza o termina su cargo dentro del período paga el mínimo mensual completo.

    TODO(negocio): en el sistema de la Caja hay mínimos proporcionales en esos meses; falta que la
    Caja defina la fórmula. Mientras tanto se cobra completo y se avisa.
    """
    desde, hasta = rango_periodo(periodo)
    avisos: list[str] = []
    for o in equipo:
        if o.modalidad not in (ModalidadBoleta.COMPLETA, ModalidadBoleta.CON_MINIMO):
            continue
        tramos = [c for c in cargos if c.escribano_id == o.escribano_id]
        empieza = min(c.fecha_desde for c in tramos) > desde
        finales = [c.fecha_hasta for c in tramos if c.fecha_hasta is not None]
        termina = len(finales) == len(tramos) and max(finales) < hasta
        if empieza or termina:
            cuando = " y ".join(
                verbo for verbo, si in (("empieza", empieza), ("termina", termina)) if si
            )
            avisos.append(
                f"{nombre_escribano(tramos[0].escribano)} {cuando} su cargo dentro del período: "
                "se cobra el mínimo mensual completo (la Caja todavía no definió un proporcional)."
            )
    return avisos


# --------------------------------------------------------------------------- vencimientos


async def list_vencimientos(session: AsyncSession, anio: int | None) -> list[Vencimiento]:
    stmt = select(Vencimiento).order_by(Vencimiento.periodo)
    if anio is not None:
        stmt = stmt.where(Vencimiento.periodo.like(f"{anio:04d}-%"))
    return list((await session.scalars(stmt)).all())


async def vencimiento_de(session: AsyncSession, periodo: str) -> date | None:
    return await session.scalar(
        select(Vencimiento.fecha_vencimiento).where(Vencimiento.periodo == periodo)
    )


async def _vencimiento_requerido(session: AsyncSession, periodo: str) -> date:
    fecha = await vencimiento_de(session, periodo)
    if fecha is None:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            f"No está cargado el vencimiento del período {_texto_periodo(periodo)}.",
            type_="urn:suite-notarial:ddjj:sin-vencimiento",
        )
    return fecha


async def fijar_vencimiento(
    session: AsyncSession, ctx: RequestContext, actor: User, periodo: str, fecha: date
) -> Vencimiento:
    """Crea o corrige el vencimiento de un período. Las boletas ya emitidas guardan el suyo."""
    _, fin = rango_periodo(periodo)
    if fecha <= fin:
        raise _invalid("El vencimiento tiene que ser posterior al último día del período.")
    item = await session.scalar(
        select(Vencimiento).where(Vencimiento.periodo == periodo).with_for_update()
    )
    anterior = item.fecha_vencimiento.isoformat() if item else None
    if item is not None and item.fecha_vencimiento != fecha:
        emitidas = await session.scalar(select(func.count()).where(Boleta.periodo == periodo))
        if emitidas:
            raise _conflict(
                f"El período {_texto_periodo(periodo)} ya tiene boletas emitidas: "
                "su vencimiento no se puede cambiar."
            )
    if item is None:
        item = Vencimiento(periodo=periodo, fecha_vencimiento=fecha, created_by_user_id=actor.id)
        session.add(item)
    else:
        item.fecha_vencimiento = fecha
    record_audit(
        session,
        ctx,
        AuditEvent.VENCIMIENTO_FIJADO,
        actor_user_id=actor.id,
        old_value={"fecha_vencimiento": anterior} if anterior else None,
        new_value={"fecha_vencimiento": fecha.isoformat()},
        details={"periodo": periodo},
    )
    await session.commit()
    return item


# --------------------------------------------------------------------------- declaraciones


@dataclass(frozen=True)
class FiltroDeclaraciones:
    registro_id: uuid.UUID | None = None
    periodo: str | None = None
    estado: EstadoDDJJ | None = None


async def list_declaraciones(
    session: AsyncSession, principal: Principal, filtro: FiltroDeclaraciones, page: PageParams
) -> tuple[list[DeclaracionJurada], int]:
    stmt = select(DeclaracionJurada)
    alcance = await _alcance_ddjj(session, principal)
    if alcance is not None:
        if not alcance:
            return [], 0
        stmt = stmt.where(
            or_(
                *(
                    a.condicion(DeclaracionJurada.registro_id, DeclaracionJurada.periodo)
                    for a in alcance
                )
            )
        )
    if filtro.registro_id:
        stmt = stmt.where(DeclaracionJurada.registro_id == filtro.registro_id)
    if filtro.periodo:
        stmt = stmt.where(DeclaracionJurada.periodo == filtro.periodo)
    if filtro.estado:
        stmt = stmt.where(DeclaracionJurada.estado == filtro.estado.value)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await session.scalars(
        stmt.order_by(
            DeclaracionJurada.periodo.desc(),
            DeclaracionJurada.registro_id,
            DeclaracionJurada.numero_rectificativa.desc(),
        )
        .offset(page.offset)
        .limit(page.page_size)
    )
    return list(result.all()), total or 0


async def get_declaracion(
    session: AsyncSession, principal: Principal, ddjj_id: uuid.UUID, *, lock: bool = False
) -> DeclaracionJurada:
    stmt = select(DeclaracionJurada).where(DeclaracionJurada.id == ddjj_id)
    if lock:
        stmt = stmt.with_for_update()
    item = await session.scalar(stmt)
    if item is None:
        raise _not_found("La declaración jurada")
    await _exigir_lectura(session, principal, item)
    return item


async def abrir_declaracion(
    session: AsyncSession, ctx: RequestContext, principal: Principal, data: DeclaracionIn
) -> tuple[DeclaracionJurada, bool]:
    """Devuelve la DDJJ en curso del registro y período, o abre el borrador."""
    registro = await session.get(RegistroNotarial, data.registro_id)
    if registro is None:
        raise _not_found("El registro notarial")
    await _exigir_operacion(session, principal, registro.id)
    if data.periodo > periodo_de(today_local()):
        raise _invalid("No se puede declarar un período que todavía no empezó.")
    existente = await session.scalar(
        select(DeclaracionJurada).where(
            DeclaracionJurada.registro_id == registro.id,
            DeclaracionJurada.periodo == data.periodo,
            DeclaracionJurada.estado != EstadoDDJJ.RECTIFICADA.value,
        )
    )
    if existente is not None:
        return existente, False
    if registro.estado == EstadoRegistro.CERRADO.value:
        raise _conflict("El registro está cerrado.")
    item = DeclaracionJurada(
        id=uuid.uuid4(),
        registro_id=registro.id,
        periodo=data.periodo,
        numero_rectificativa=0,
        estado=EstadoDDJJ.BORRADOR.value,
        created_by_user_id=principal.user.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.DDJJ_ABIERTA,
        actor_user_id=principal.user.id,
        details={
            "ddjj_id": str(item.id),
            "registro": registro.numero_registro,
            "periodo": data.periodo,
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        # Otra sesión abrió el mismo borrador en paralelo: se devuelve ese.
        await session.rollback()
        otro = await session.scalar(
            select(DeclaracionJurada).where(
                DeclaracionJurada.registro_id == registro.id,
                DeclaracionJurada.periodo == data.periodo,
                DeclaracionJurada.estado != EstadoDDJJ.RECTIFICADA.value,
            )
        )
        if otro is None:
            raise
        return otro, False
    await session.refresh(item)
    return item, True


async def list_actos(session: AsyncSession, ddjj_id: uuid.UUID) -> list[Acto]:
    result = await session.execute(
        select(Acto)
        .where(Acto.ddjj_id == ddjj_id, Acto.is_active.is_(True))
        .order_by(Acto.tipo_protocolo.desc(), Acto.numero_escritura)
    )
    return list(result.unique().scalars())


def _exigir_borrador(ddjj: DeclaracionJurada) -> None:
    if ddjj.estado != EstadoDDJJ.BORRADOR.value:
        raise _conflict(
            "La declaración jurada ya fue presentada: se corrige con una rectificativa."
        )


ACTO_FIELDS = (
    "escribano_id",
    "cargo",
    "tipo_protocolo",
    "numero_escritura",
    "orden_en_escritura",
    "folio",
    "fecha_acto",
    "naturaleza",
    "categoria",
    "base_imponible",
    "motivo_exencion",
    "detalle_exencion",
    "vademecum_id",
    "fuera_de_vademecum",
    "precio",
    "avaluo",
    "mismas_partes",
)


def _acto_values(acto: Acto) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in ACTO_FIELDS:
        value = getattr(acto, field)
        if isinstance(value, date | uuid.UUID):
            value = str(value)
        elif isinstance(value, Decimal):
            value = f"{value:.2f}"
        values[field] = value
    return values


async def agregar_acto(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    ddjj_id: uuid.UUID,
    data: ActoIn,
    *,
    acto_id: uuid.UUID | None = None,
) -> Acto:
    """`acto_id` lo fija quien necesita referenciar el acto en la misma transacción (p. ej. la
    ratificación de una sugerencia de IA): el commit es uno solo."""
    ddjj = await get_declaracion(session, principal, ddjj_id, lock=True)
    await _exigir_operacion(session, principal, ddjj.registro_id)
    _exigir_borrador(ddjj)
    desde, hasta = rango_periodo(ddjj.periodo)
    if not desde <= data.fecha_acto <= hasta:
        raise _invalid(
            f"La fecha del acto tiene que estar dentro del período {_texto_periodo(ddjj.periodo)}."
        )
    if data.fecha_acto > today_local():
        raise _invalid("La fecha del acto no puede ser futura.")
    cargo = await a_cargo.habilitacion(
        session, ddjj.registro_id, data.escribano_id, data.fecha_acto
    )
    if cargo is None:
        raise _invalid("El escribano no tenía cargo en este registro a la fecha del acto.")
    fuera_de_vademecum = await _segun_vademecum(session, data, desde)
    # La fecha ya está dentro del período: el año del protocolo es el del período.
    anio = int(ddjj.periodo[:4])
    await _bloquear_protocolo(session, ddjj.registro_id, anio)
    if len(await list_actos(session, ddjj.id)) >= MAX_ACTOS_POR_DDJJ:
        raise _conflict(f"Una declaración jurada admite hasta {MAX_ACTOS_POR_DDJJ} actos.")
    vista = protocolo.Vista(
        await actos_del_anio(session, ddjj.registro_id, anio),
        await _visible(session, principal, ddjj.registro_id),
    )
    candidato = protocolo.Candidato(
        data.tipo_protocolo.value,
        data.numero_escritura,
        data.folio,
        data.fecha_acto,
        ddjj_id=ddjj.id,
        multiple=data.acto_multiple,
    )
    for control in protocolo.revisar(vista, candidato):
        if control.nivel is protocolo.NivelControl.BLOQUEANTE:
            raise _conflict(control.mensaje)
    orden = await _orden_en_escritura(session, ddjj, data)
    hermanos = await _misma_escritura(session, ddjj, data) if orden > 1 else []
    # Un acto suelto no tiene a quién agruparse: la respuesta se pide al cargar el segundo acto
    # de la escritura (ActoIn la exige en un acto múltiple).
    mismas_partes = True if data.mismas_partes is None else data.mismas_partes
    for hermano in hermanos:
        # Las mismas partes valen para toda la escritura: la respuesta del último acto rige, y
        # cada acto que cambia queda en la auditoría con su valor anterior.
        if hermano.mismas_partes != mismas_partes:
            record_audit(
                session,
                ctx,
                AuditEvent.DDJJ_ACTO_PARTES_ACTUALIZADAS,
                actor_user_id=principal.user.id,
                old_value={"mismas_partes": hermano.mismas_partes},
                new_value={"mismas_partes": mismas_partes},
                details={"ddjj_id": str(ddjj.id), "acto_id": str(hermano.id)},
            )
            hermano.mismas_partes = mismas_partes
    item = Acto(
        id=acto_id or uuid.uuid4(),
        ddjj_id=ddjj.id,
        escribano_id=data.escribano_id,
        cargo=cargo.cargo,
        tipo_protocolo=data.tipo_protocolo.value,
        numero_escritura=data.numero_escritura,
        orden_en_escritura=orden,
        folio=data.folio,
        fecha_acto=data.fecha_acto,
        naturaleza=data.naturaleza,
        categoria=data.categoria.value,
        base_imponible=data.base_imponible,
        motivo_exencion=data.motivo_exencion.value if data.motivo_exencion else None,
        detalle_exencion=data.detalle_exencion,
        vademecum_id=data.vademecum_id,
        fuera_de_vademecum=fuera_de_vademecum,
        precio=data.precio,
        avaluo=data.avaluo,
        mismas_partes=mismas_partes,
        created_by_user_id=principal.user.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.DDJJ_ACTO_AGREGADO,
        actor_user_id=principal.user.id,
        new_value=_acto_values(item),
        details={
            "ddjj_id": str(ddjj.id),
            "acto_id": str(item.id),
            **(
                {"mismas_partes_escritura": mismas_partes, "actos_de_la_escritura": orden}
                if hermanos
                else {}
            ),
        },
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # Solo la carrera contra el índice único es un duplicado; cualquier otra violación es
        # un error interno y no se disfraza de escritura repetida.
        restriccion = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
        if restriccion != "uq_ddjj_actos_escritura":
            raise
        raise _conflict(
            f"La escritura N° {data.numero_escritura} del protocolo "
            f"{data.tipo_protocolo.value.lower()} ya está declarada en esta DDJJ."
        ) from exc
    result = await session.execute(select(Acto).where(Acto.id == item.id))
    return result.unique().scalar_one()


# --------------------------------------------------------------------------- libro de protocolo


async def proximos_numeros(
    session: AsyncSession, principal: Principal, registro_id: uuid.UUID, anio: int
) -> dict[TipoProtocolo, int]:
    """Número de escritura que sigue en cada protocolo del registro (la numeración es anual):
    lo que la carga rápida propone para el próximo acto. Solo cuenta los meses que quien
    consulta puede ver, como los demás controles del libro."""
    visible = await _visible(session, principal, registro_id)
    ultimos = {t: 0 for t in TipoProtocolo}
    for acto in await actos_del_anio(session, registro_id, anio):
        if not visible(acto.periodo):
            continue
        tipo = TipoProtocolo(acto.tipo_protocolo)
        ultimos[tipo] = max(ultimos[tipo], acto.numero)
    return {t: n + 1 for t, n in ultimos.items()}


async def actos_del_anio(
    session: AsyncSession, registro_id: uuid.UUID, anio: int
) -> list[protocolo.ActoDeclarado]:
    """Actos vigentes del registro con fecha en el año, en DDJJ no reemplazadas por una
    rectificativa (los de la rectificada viven en su rectificativa)."""
    filas = await session.execute(
        select(
            Acto.id,
            Acto.ddjj_id,
            Acto.tipo_protocolo,
            Acto.numero_escritura,
            Acto.folio,
            Acto.fecha_acto,
            DeclaracionJurada.periodo,
        )
        .join(DeclaracionJurada, DeclaracionJurada.id == Acto.ddjj_id)
        .where(
            DeclaracionJurada.registro_id == registro_id,
            DeclaracionJurada.estado != EstadoDDJJ.RECTIFICADA.value,
            Acto.is_active.is_(True),
            Acto.fecha_acto >= date(anio, 1, 1),
            Acto.fecha_acto <= date(anio, 12, 31),
        )
    )
    return [protocolo.ActoDeclarado(*fila) for fila in filas.all()]


async def _segun_vademecum(session: AsyncSession, data: ActoIn, inicio: date) -> bool:
    """Valida el acto contra el vademécum que rige el período y dice si queda fuera de él.

    Con `vademecum_id`, la categoría y la exención tienen que ser las del vademécum (la pantalla
    las toma de ahí; el servidor no confía en lo que manda). Sin él, el acto queda marcado para
    revisión de la Caja si el período tiene vademécum; una escritura sin efecto no es un acto.
    """
    if data.vademecum_id is None:
        if data.categoria is CategoriaActo.SIN_EFECTO:
            return False
        return bool(await vademecum.vigentes(session, inicio))
    item = await session.get(VademecumActo, data.vademecum_id)
    if item is None or not vademecum.vigente_el(item, inicio):
        raise _invalid("Ese acto del vademécum no rige para el período de la declaración.")
    if data.categoria.value != item.categoria or (
        (data.motivo_exencion.value if data.motivo_exencion else None) != item.motivo_exencion
    ):
        raise _invalid(
            f"«{item.nombre}» aporta como {item.categoria}: la categoría del acto tiene que ser "
            "la del vademécum."
        )
    return False


async def _misma_escritura(
    session: AsyncSession, ddjj: DeclaracionJurada, data: ActoIn
) -> list[Acto]:
    return [
        a
        for a in await list_actos(session, ddjj.id)
        if a.tipo_protocolo == data.tipo_protocolo.value
        and a.numero_escritura == data.numero_escritura
    ]


async def _orden_en_escritura(session: AsyncSession, ddjj: DeclaracionJurada, data: ActoIn) -> int:
    """1 para el primer acto de una escritura; para un acto múltiple, el siguiente de su
    escritura, que tiene que estar cargada en esta DDJJ y con la misma fecha."""
    if not data.acto_multiple:
        return 1
    hermanos = await _misma_escritura(session, ddjj, data)
    if not hermanos:
        raise _invalid(
            f"La escritura N° {data.numero_escritura} no está cargada en esta declaración: "
            "cargá primero su primer acto y después los demás como acto múltiple."
        )
    if any(a.fecha_acto != data.fecha_acto for a in hermanos):
        raise _invalid(
            f"Un acto múltiple lleva la fecha de su escritura ({hermanos[0].fecha_acto:%d/%m/%Y})."
        )
    return max(a.orden_en_escritura for a in hermanos) + 1


async def _bloquear_protocolo(session: AsyncSession, registro_id: uuid.UUID, anio: int) -> None:
    """Serializa las altas de actos de un registro en un año: el control de número repetido
    entre DDJJ de distintos meses y la inserción quedan en la misma sección crítica."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:clave, 0))"),
        {"clave": f"ddjj-protocolo:{registro_id}:{anio}"},
    )


async def _visible(
    session: AsyncSession, principal: Principal, registro_id: uuid.UUID
) -> Callable[[str], bool]:
    """Si quien consulta puede ver la DDJJ de un período del registro (para no citar número,
    folio ni fecha de escrituras fuera de su alcance)."""
    alcance = await _alcance_ddjj(session, principal)
    if alcance is None:
        return lambda _periodo: True
    return lambda periodo: any(a.incluye(registro_id, periodo) for a in alcance)


async def controles_ddjj(
    session: AsyncSession, principal: Principal, ddjj: DeclaracionJurada, actos: list[Acto]
) -> tuple[dict[uuid.UUID, list[protocolo.Control]], list[protocolo.Hueco]]:
    """Controles de cada acto de la DDJJ y números salteados del año del período."""
    vista = protocolo.Vista(
        await actos_del_anio(session, ddjj.registro_id, int(ddjj.periodo[:4])),
        await _visible(session, principal, ddjj.registro_id),
    )
    por_acto: dict[uuid.UUID, list[protocolo.Control]] = {}
    for a in actos:
        candidato = protocolo.Candidato(
            a.tipo_protocolo,
            a.numero_escritura,
            a.folio,
            a.fecha_acto,
            ddjj_id=a.ddjj_id,
            multiple=True,
            excluir=a.id,
        )
        controles = protocolo.revisar(vista, candidato)
        if controles:
            por_acto[a.id] = controles
    return por_acto, protocolo.huecos(vista)


async def _exigir_numeracion_sin_repetidos(
    session: AsyncSession, principal: Principal, ddjj: DeclaracionJurada, actos: list[Acto]
) -> None:
    """Ninguna escritura de la DDJJ puede estar declarada en otra DDJJ del año (red de
    seguridad al presentar, además del control al cargar)."""
    anio = int(ddjj.periodo[:4])
    await _bloquear_protocolo(session, ddjj.registro_id, anio)
    vista = protocolo.Vista(
        await actos_del_anio(session, ddjj.registro_id, anio),
        await _visible(session, principal, ddjj.registro_id),
    )
    for a in actos:
        candidato = protocolo.Candidato(
            a.tipo_protocolo,
            a.numero_escritura,
            a.folio,
            a.fecha_acto,
            ddjj_id=a.ddjj_id,
            multiple=True,
            excluir=a.id,
        )
        for control in protocolo.revisar(vista, candidato):
            if control.nivel is protocolo.NivelControl.BLOQUEANTE:
                raise _conflict(f"No se puede presentar: {control.mensaje}")


async def verificar_acto(
    session: AsyncSession, principal: Principal, ddjj_id: uuid.UUID, data: VerificacionActoIn
) -> tuple[Decimal | None, list[protocolo.Control]]:
    """Aporte estimado y controles de un acto a medio cargar (no guarda nada)."""
    ddjj = await get_declaracion(session, principal, ddjj_id)
    await _exigir_operacion(session, principal, ddjj.registro_id)
    # El año sale del período (no de la fecha que manda el cliente): un acto solo puede tener
    # fecha dentro del período de su DDJJ.
    desde, hasta = rango_periodo(ddjj.periodo)
    fecha = data.fecha_acto if data.fecha_acto and desde <= data.fecha_acto <= hasta else None
    controles = protocolo.revisar(
        protocolo.Vista(
            await actos_del_anio(session, ddjj.registro_id, int(ddjj.periodo[:4])),
            await _visible(session, principal, ddjj.registro_id),
        ),
        protocolo.Candidato(
            data.tipo_protocolo.value,
            data.numero_escritura,
            data.folio,
            fecha,
            ddjj_id=ddjj.id,
            multiple=data.acto_multiple,
            excluir=data.excluir_acto_id,
        ),
    )
    aporte = None
    if data.categoria is not None:
        codigo = CONCEPTO_POR_CATEGORIA[data.categoria]
        vigencia = None
        if codigo is not None:
            inicio, _ = rango_periodo(ddjj.periodo)
            try:
                vigencia = await parametros.get_vigencia(session, codigo, inicio)
            except ProblemError:
                vigencia = None
        try:
            base = base_de(data.precio, data.avaluo) or data.base_imponible or Decimal("0")
            aporte = aporte_de_acto(ActoALiquidar(data.categoria, base), vigencia).aporte
        except LiquidacionError:
            aporte = None
    return aporte, controles


async def baja_acto(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    ddjj_id: uuid.UUID,
    acto_id: uuid.UUID,
    motivo: str,
) -> None:
    ddjj = await get_declaracion(session, principal, ddjj_id, lock=True)
    await _exigir_operacion(session, principal, ddjj.registro_id)
    _exigir_borrador(ddjj)
    result = await session.execute(
        select(Acto).where(Acto.id == acto_id, Acto.ddjj_id == ddjj.id, Acto.is_active.is_(True))
    )
    acto = result.unique().scalars().first()
    if acto is None:
        raise _not_found("El acto")
    acto.is_active = False
    record_audit(
        session,
        ctx,
        AuditEvent.DDJJ_ACTO_BAJA,
        actor_user_id=principal.user.id,
        old_value=_acto_values(acto),
        details={"ddjj_id": str(ddjj.id), "acto_id": str(acto.id), "motivo": motivo},
    )
    await session.commit()


# --------------------------------------------------------------------------- liquidación


@dataclass(frozen=True)
class Preliquidacion:
    # Aporte de cada acto, en el orden de los actos.
    aportes: tuple[AporteActo, ...]
    # Una por escribano con boleta, en el orden del equipo (titular primero).
    boletas: tuple[LiquidacionEscribano, ...]
    escribanos: dict[uuid.UUID, Escribano]
    avisos: list[str]
    vencimiento: date
    fecha_pago: date
    minimo: VigenciaSnapshot
    medico: VigenciaSnapshot
    mora: list[VigenciaSnapshot]
    usa_valores_de_ejemplo: bool
    pluralidad: VigenciaSnapshot | None = None

    @property
    def total_protocolos(self) -> Decimal:
        """Aportes de todos los actos del registro (la suma de lo que va a cada boleta)."""
        return to_money(sum((a.aporte for a in self.aportes), Decimal("0.00")))


async def _hay_ejemplos(session: AsyncSession, ids: set[uuid.UUID]) -> bool:
    if not ids:
        return False
    return bool(
        await session.scalar(
            select(func.count()).where(Vigencia.id.in_(ids), Vigencia.es_ejemplo.is_(True))
        )
    )


async def _tasas_de_mora(
    session: AsyncSession, vencimiento: date, fecha_pago: date
) -> list[VigenciaSnapshot]:
    """Tasas de mora vigentes del vencimiento a la fecha de pago: cada tramo de días de atraso
    se calcula con la suya (la Caja lo pidió así)."""
    if fecha_pago <= vencimiento:
        return []
    return await parametros.vigencias_entre(session, CONCEPTO_MORA, vencimiento, fecha_pago)


async def preliquidar(
    session: AsyncSession, ddjj: DeclaracionJurada, actos: list[Acto], fecha_pago: date
) -> Preliquidacion:
    """Liquidación de un borrador con los parámetros vigentes al primer día del período."""
    inicio, _ = rango_periodo(ddjj.periodo)
    vencimiento = await _vencimiento_requerido(session, ddjj.periodo)
    por_concepto: dict[str, VigenciaSnapshot] = {}
    a_liquidar: list[tuple[uuid.UUID, ActoALiquidar, VigenciaSnapshot | None]] = []
    for acto in actos:
        categoria = CategoriaActo(acto.categoria)
        codigo = CONCEPTO_POR_CATEGORIA[categoria]
        vigencia = None
        if codigo is not None:
            if codigo not in por_concepto:
                por_concepto[codigo] = await parametros.get_vigencia(session, codigo, inicio)
            vigencia = por_concepto[codigo]
        a_liquidar.append(
            (
                acto.escribano_id,
                ActoALiquidar(
                    categoria,
                    acto.base_imponible,
                    escritura=(acto.tipo_protocolo, acto.numero_escritura),
                    mismas_partes=acto.mismas_partes,
                ),
                vigencia,
            )
        )
    minimo = await parametros.get_vigencia(session, CONCEPTO_MINIMO, inicio)
    medico = await parametros.get_vigencia(session, CONCEPTO_MEDICO, inicio)
    pluralidad = await parametros.vigencia_opcional(session, CONCEPTO_PLURALIDAD, inicio)
    mora = await _tasas_de_mora(session, vencimiento, fecha_pago)
    cargos = await cargos_en_periodo(session, ddjj.registro_id, ddjj.periodo)
    equipo = obligados(cargos)
    try:
        aportes, boletas = liquidar_por_escribano(
            a_liquidar,
            equipo,
            minimo=minimo,
            medico=medico,
            vencimiento=vencimiento,
            fecha_pago=fecha_pago,
            mora=mora,
            pluralidad=pluralidad,
        )
    except LiquidacionError as exc:
        raise _invalid(str(exc)) from exc
    usadas = {v.vigencia_id for v in por_concepto.values()} | {minimo.vigencia_id}
    usadas |= {medico.vigencia_id} | {v.vigencia_id for v in mora}
    return Preliquidacion(
        aportes=aportes,
        boletas=boletas,
        escribanos={c.escribano_id: c.escribano for c in cargos},
        avisos=avisos_de_minimo(cargos, equipo, ddjj.periodo),
        vencimiento=vencimiento,
        fecha_pago=fecha_pago,
        minimo=minimo,
        medico=medico,
        mora=mora,
        usa_valores_de_ejemplo=await _hay_ejemplos(session, usadas),
        pluralidad=pluralidad,
    )


def _validar_fecha_pago(fecha_pago: date) -> None:
    hoy = today_local()
    if fecha_pago < hoy:
        raise _invalid("La fecha de pago no puede ser anterior a hoy.")
    if fecha_pago > hoy + timedelta(days=MAX_DIAS_VALIDEZ_BOLETA):
        raise _invalid(
            f"La fecha de pago puede ser, como máximo, dentro de {MAX_DIAS_VALIDEZ_BOLETA} días."
        )


# --------------------------------------------------------------------------- boletas


def nuevo_codigo_verificacion() -> str:
    """16 caracteres base32 (80 bits): imposible de adivinar, fácil de dictar o tipear."""
    return base64.b32encode(secrets.token_bytes(10)).decode("ascii")


def checksum_boleta(boleta: Boleta, registro_numero: int) -> str:
    """Huella SHA-256 de los datos impresos: permite detectar cualquier alteración posterior."""
    datos = {
        "numero": boleta.numero,
        "codigo": boleta.codigo_verificacion,
        "registro": registro_numero,
        "periodo": boleta.periodo,
        "fecha_emision": boleta.fecha_emision.isoformat(),
        "fecha_vencimiento": boleta.fecha_vencimiento.isoformat(),
        "fecha_pago": boleta.fecha_pago.isoformat(),
        "dias_mora": boleta.dias_mora,
        "total_protocolos": f"{boleta.total_protocolos:.2f}",
        "aporte_minimo": f"{boleta.aporte_minimo:.2f}",
        "excedente": f"{boleta.excedente:.2f}",
        "aporte_medico": f"{boleta.aporte_medico:.2f}",
        "cantidad_aportes_medicos": boleta.cantidad_aportes_medicos,
        "total_en_termino": f"{boleta.total_en_termino:.2f}",
        "interes_mora": f"{boleta.interes_mora:.2f}",
        "total_a_pagar": f"{boleta.total_a_pagar:.2f}",
        "vigencias": [
            str(boleta.vigencia_minimo_id),
            str(boleta.vigencia_medico_id),
            str(boleta.vigencia_mora_id) if boleta.vigencia_mora_id else None,
        ],
    }
    # Las boletas del registro (anteriores a las boletas por notario) no lo tienen.
    if boleta.escribano_id is not None:
        datos["escribano"] = str(boleta.escribano_id)
        datos["cargo"] = boleta.cargo
        datos["modalidad"] = boleta.modalidad
    # Las boletas anteriores al detalle por tramos no lo tienen: su huella no cambia.
    if boleta.tramos_mora:
        datos["tramos_mora"] = [
            {
                "desde": t.desde.isoformat(),
                "hasta": t.hasta.isoformat(),
                "dias": t.dias,
                "vigencia": str(t.vigencia_id),
                "tasa": f"{t.tasa:.4f}",
                "periodo_tasa": t.periodo_tasa,
                "interes": f"{t.interes:.2f}",
            }
            for t in boleta.tramos_mora
        ]
    canon = json.dumps(datos, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canon.encode("ascii")).hexdigest()


async def _crear_boleta(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    ddjj: DeclaracionJurada,
    *,
    liquidacion: Liquidacion,
    vencimiento: date,
    fecha_pago: date,
    vigencia_minimo_id: uuid.UUID,
    vigencia_medico_id: uuid.UUID,
    escribano_id: uuid.UUID | None,
    cargo: str | None,
    modalidad: str | None,
) -> Boleta:
    registro = await session.get(RegistroNotarial, ddjj.registro_id)
    assert registro is not None  # noqa: S101 - FK RESTRICT
    numero = await session.scalar(text("SELECT nextval('ddjj_boletas_numero_seq')"))
    boleta = Boleta(
        id=uuid.uuid4(),
        numero=numero,
        codigo_verificacion=nuevo_codigo_verificacion(),
        ddjj_id=ddjj.id,
        registro_id=ddjj.registro_id,
        periodo=ddjj.periodo,
        estado=EstadoBoleta.PENDIENTE.value,
        escribano_id=escribano_id,
        cargo=cargo,
        modalidad=modalidad,
        fecha_emision=today_local(),
        fecha_vencimiento=vencimiento,
        fecha_pago=fecha_pago,
        dias_mora=liquidacion.dias_mora,
        total_protocolos=liquidacion.total_protocolos,
        aporte_minimo=liquidacion.aporte_minimo,
        excedente=liquidacion.excedente,
        aporte_medico=liquidacion.aporte_medico,
        cantidad_aportes_medicos=liquidacion.cantidad_aportes_medicos,
        total_en_termino=liquidacion.total_en_termino,
        interes_mora=liquidacion.interes_mora,
        total_a_pagar=liquidacion.total_a_pagar,
        vigencia_minimo_id=vigencia_minimo_id,
        vigencia_medico_id=vigencia_medico_id,
        # La tasa vigente al vencimiento; el detalle por tramo, en `tramos_mora`.
        vigencia_mora_id=(
            liquidacion.tramos_mora[0].vigencia.vigencia_id if liquidacion.tramos_mora else None
        ),
        emitida_por_user_id=actor.id,
        checksum_sha256="",
    )
    boleta.tramos_mora = [
        BoletaTramoMora(
            orden=i,
            desde=t.desde,
            hasta=t.hasta,
            dias=t.dias,
            vigencia_id=t.vigencia.vigencia_id,
            tasa=t.tasa,
            periodo_tasa=t.periodo_tasa.value,
            interes=t.interes,
        )
        for i, t in enumerate(liquidacion.tramos_mora, start=1)
    ]
    boleta.checksum_sha256 = checksum_boleta(boleta, registro.numero_registro)
    session.add(boleta)
    record_audit(
        session,
        ctx,
        AuditEvent.BOLETA_EMITIDA,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        new_value={
            "numero": numero,
            "total_a_pagar": f"{boleta.total_a_pagar:.2f}",
            "fecha_pago": fecha_pago.isoformat(),
            "checksum_sha256": boleta.checksum_sha256,
        },
        details={
            "boleta_id": str(boleta.id),
            "ddjj_id": str(ddjj.id),
            "registro": registro.numero_registro,
            "periodo": ddjj.periodo,
            "escribano_id": str(escribano_id) if escribano_id else None,
            "modalidad": modalidad,
        },
    )
    return boleta


async def _boletas_pendientes(session: AsyncSession, ddjj_id: uuid.UUID) -> list[Boleta]:
    result = await session.scalars(
        select(Boleta)
        .where(Boleta.ddjj_id == ddjj_id, Boleta.estado == EstadoBoleta.PENDIENTE.value)
        .order_by(Boleta.numero)
        .with_for_update()
    )
    return list(result.all())


def _de(escribano_id: uuid.UUID | None) -> ColumnElement[bool]:
    """Boletas de ese escribano (None: las del registro, anteriores a las boletas por notario)."""
    return Boleta.escribano_id.is_not_distinct_from(escribano_id)


def _anular(
    session: AsyncSession, ctx: RequestContext, actor: User, boleta: Boleta, motivo: str
) -> None:
    boleta.estado = EstadoBoleta.ANULADA.value
    boleta.anulada_en = datetime.now(UTC)
    boleta.motivo_anulacion = motivo
    record_audit(
        session,
        ctx,
        AuditEvent.BOLETA_ANULADA,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value={"estado": EstadoBoleta.PENDIENTE.value},
        new_value={"estado": EstadoBoleta.ANULADA.value},
        details={"boleta_id": str(boleta.id), "numero": boleta.numero, "motivo": motivo},
    )


async def presentar(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    ddjj_id: uuid.UUID,
    data: PresentarIn,
) -> list[Boleta]:
    """Congela la liquidación de cada acto y emite la boleta de cada escribano del equipo en la
    misma transacción (todas con la fecha de pago elegida; cada uno puede reemitir la suya)."""
    ddjj = await get_declaracion(session, principal, ddjj_id, lock=True)
    await _exigir_operacion(session, principal, ddjj.registro_id)
    _exigir_borrador(ddjj)
    if ddjj.periodo >= periodo_de(today_local()):
        raise _invalid("La declaración jurada se presenta una vez terminado el período.")
    _validar_fecha_pago(data.fecha_pago)
    actos = await list_actos(session, ddjj.id)
    await _exigir_numeracion_sin_repetidos(session, principal, ddjj, actos)
    pre = await preliquidar(session, ddjj, actos, data.fecha_pago)
    for acto, aporte in zip(actos, pre.aportes, strict=True):
        acto.aporte = aporte.aporte
        acto.vigencia_id = aporte.vigencia.vigencia_id if aporte.vigencia else None
        acto.aporte_individual = aporte.aporte_individual
        acto.vigencia_pluralidad_id = aporte.pluralidad.vigencia_id if aporte.pluralidad else None
    await session.flush()
    ddjj.estado = EstadoDDJJ.PRESENTADA.value
    ddjj.fecha_presentacion = datetime.now(UTC)
    ddjj.presentada_por_user_id = principal.user.id
    ddjj.total_protocolos = pre.total_protocolos
    ddjj.cantidad_actos = len(actos)
    if data.observaciones:
        ddjj.observaciones = data.observaciones
    record_audit(
        session,
        ctx,
        AuditEvent.DDJJ_PRESENTADA,
        severity=Severity.WARNING,
        actor_user_id=principal.user.id,
        old_value={"estado": EstadoDDJJ.BORRADOR.value},
        new_value={
            "estado": EstadoDDJJ.PRESENTADA.value,
            "cantidad_actos": len(actos),
            "total_protocolos": f"{pre.total_protocolos:.2f}",
            "boletas": len(pre.boletas),
        },
        details={"ddjj_id": str(ddjj.id), "periodo": ddjj.periodo},
    )
    boletas = [
        await _crear_boleta(
            session,
            ctx,
            principal.user,
            ddjj,
            liquidacion=b.liquidacion,
            vencimiento=pre.vencimiento,
            fecha_pago=data.fecha_pago,
            vigencia_minimo_id=pre.minimo.vigencia_id,
            vigencia_medico_id=pre.medico.vigencia_id,
            escribano_id=b.obligado.escribano_id,
            cargo=b.obligado.cargo,
            modalidad=b.modalidad.value,
        )
        for b in pre.boletas
    ]
    await session.commit()
    return boletas


async def _exigir_sin_comprobante_en_revision(
    session: AsyncSession, ddjj_id: uuid.UUID, *, solo: ColumnElement[bool] | None = None
) -> None:
    """Mientras Tesorería revisa un pago, la boleta no se anula (regla PAGO). `solo` acota a
    las boletas de un escribano."""
    condiciones = [
        Boleta.ddjj_id == ddjj_id,
        Comprobante.estado == EstadoComprobante.PENDIENTE_REVISION.value,
    ]
    if solo is not None:
        condiciones.append(solo)
    en_revision = await session.scalar(
        select(func.count())
        .select_from(Comprobante)
        .join(Boleta, Boleta.id == Comprobante.boleta_id)
        .where(*condiciones)
    )
    if en_revision:
        raise _conflict(
            "Hay un comprobante de pago en revisión por Tesorería: esperá su respuesta antes "
            "de cambiar la boleta."
        )


async def emitir_boleta(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    ddjj_id: uuid.UUID,
    fecha_pago: date,
    escribano_id: uuid.UUID | None,
) -> Boleta:
    """Nueva boleta de un escribano para otra fecha de pago (recalcula solo la mora).

    Los importes de protocolo, mínimo y aporte médico salen de su primera boleta de la DDJJ
    (SNAP): un cambio posterior de parámetros no los altera. Su boleta pendiente anterior se
    anula; las de los demás escribanos no cambian. `escribano_id` None: la boleta del registro,
    en las DDJJ presentadas antes de las boletas por notario.
    """
    ddjj = await get_declaracion(session, principal, ddjj_id, lock=True)
    await _exigir_operacion(session, principal, ddjj.registro_id)
    if ddjj.estado != EstadoDDJJ.PRESENTADA.value:
        raise _conflict("Solo se emiten boletas de una declaración jurada presentada.")
    if not await puede_reemitir(session, principal, ddjj.registro_id, escribano_id):
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "Cada escribano reemite su propia boleta: la de otro la reemite él o la Caja.",
        )
    _validar_fecha_pago(fecha_pago)
    suyas = _de(escribano_id)
    base = await session.scalar(
        select(Boleta).where(Boleta.ddjj_id == ddjj.id, suyas).order_by(Boleta.numero).limit(1)
    )
    if base is None:
        raise _conflict("Ese escribano no tiene boleta en esta declaración jurada.")
    await _exigir_sin_comprobante_en_revision(session, ddjj.id, solo=suyas)
    if await session.scalar(
        select(func.count()).where(
            Boleta.ddjj_id == ddjj.id, suyas, Boleta.estado == EstadoBoleta.PAGADA.value
        )
    ):
        raise _conflict("Esa boleta ya está paga.")
    mora = await _tasas_de_mora(session, base.fecha_vencimiento, fecha_pago)
    try:
        liquidacion = totalizar(
            (),
            base.total_protocolos,
            aporte_minimo=base.aporte_minimo,
            aporte_medico=base.aporte_medico,
            cantidad_aportes_medicos=base.cantidad_aportes_medicos,
            vencimiento=base.fecha_vencimiento,
            fecha_pago=fecha_pago,
            mora=mora,
        )
    except LiquidacionError as exc:
        raise _invalid(str(exc)) from exc
    for pendiente in await _boletas_pendientes(session, ddjj.id):
        if pendiente.escribano_id == escribano_id:
            _anular(session, ctx, principal.user, pendiente, "Reemplazada por una boleta nueva.")
    await session.flush()
    boleta = await _crear_boleta(
        session,
        ctx,
        principal.user,
        ddjj,
        liquidacion=liquidacion,
        vencimiento=base.fecha_vencimiento,
        fecha_pago=fecha_pago,
        vigencia_minimo_id=base.vigencia_minimo_id,
        vigencia_medico_id=base.vigencia_medico_id,
        escribano_id=base.escribano_id,
        cargo=base.cargo,
        modalidad=base.modalidad,
    )
    await session.commit()
    return boleta


async def rectificar(
    session: AsyncSession, ctx: RequestContext, principal: Principal, ddjj_id: uuid.UUID
) -> DeclaracionJurada:
    """Abre la rectificativa de una DDJJ presentada, con una copia editable de sus actos.

    La original pasa a RECTIFICADA (queda intacta como antecedente) y sus boletas pendientes se
    anulan. TODO(negocio): rectificar una DDJJ con alguna boleta paga requiere definir cómo se
    imputa lo pagado.
    """
    original = await get_declaracion(session, principal, ddjj_id, lock=True)
    await _exigir_operacion(session, principal, original.registro_id)
    if original.estado != EstadoDDJJ.PRESENTADA.value:
        raise _conflict("Solo se rectifica una declaración jurada presentada.")
    if await session.scalar(
        select(func.count()).where(
            Boleta.ddjj_id == original.id, Boleta.estado == EstadoBoleta.PAGADA.value
        )
    ):
        raise _conflict(
            "La declaración jurada tiene boletas pagas: la rectificación con pago a cuenta "
            "todavía no está disponible."
        )
    await _exigir_sin_comprobante_en_revision(session, original.id)
    for pendiente in await _boletas_pendientes(session, original.id):
        _anular(session, ctx, principal.user, pendiente, "DDJJ en rectificación.")
    original.estado = EstadoDDJJ.RECTIFICADA.value
    await session.flush()
    nueva = DeclaracionJurada(
        id=uuid.uuid4(),
        registro_id=original.registro_id,
        periodo=original.periodo,
        numero_rectificativa=original.numero_rectificativa + 1,
        estado=EstadoDDJJ.BORRADOR.value,
        rectifica_a_id=original.id,
        created_by_user_id=principal.user.id,
    )
    session.add(nueva)
    for acto in await list_actos(session, original.id):
        session.add(
            Acto(
                ddjj_id=nueva.id,
                escribano_id=acto.escribano_id,
                cargo=acto.cargo,
                tipo_protocolo=acto.tipo_protocolo,
                numero_escritura=acto.numero_escritura,
                orden_en_escritura=acto.orden_en_escritura,
                folio=acto.folio,
                fecha_acto=acto.fecha_acto,
                naturaleza=acto.naturaleza,
                categoria=acto.categoria,
                base_imponible=acto.base_imponible,
                motivo_exencion=acto.motivo_exencion,
                detalle_exencion=acto.detalle_exencion,
                vademecum_id=acto.vademecum_id,
                fuera_de_vademecum=acto.fuera_de_vademecum,
                precio=acto.precio,
                avaluo=acto.avaluo,
                mismas_partes=acto.mismas_partes,
                created_by_user_id=principal.user.id,
            )
        )
    record_audit(
        session,
        ctx,
        AuditEvent.DDJJ_RECTIFICATIVA_ABIERTA,
        severity=Severity.WARNING,
        actor_user_id=principal.user.id,
        old_value={"estado": EstadoDDJJ.PRESENTADA.value},
        new_value={"estado": EstadoDDJJ.RECTIFICADA.value},
        details={
            "ddjj_id": str(original.id),
            "rectificativa_id": str(nueva.id),
            "numero_rectificativa": nueva.numero_rectificativa,
            "periodo": original.periodo,
        },
    )
    await session.commit()
    await session.refresh(nueva)
    return nueva


async def list_boletas(session: AsyncSession, ddjj_id: uuid.UUID) -> list[Boleta]:
    result = await session.scalars(
        select(Boleta).where(Boleta.ddjj_id == ddjj_id).order_by(Boleta.numero.desc())
    )
    return list(result.all())


async def alcance_boletas(session: AsyncSession, principal: Principal) -> list[Alcance] | None:
    """Boletas visibles: todas (`boletas:read_all`) o las de los meses con cargo propio."""
    return await _alcance_lectura(
        session, principal, todo=(Perm.BOLETAS_READ_ALL,), propio=Perm.BOLETAS_READ_OWN
    )


async def get_boleta(
    session: AsyncSession, principal: Principal, boleta_id: uuid.UUID, *, lock: bool = False
) -> Boleta:
    boleta = await session.get(Boleta, boleta_id, with_for_update=lock)
    if boleta is None:
        raise _not_found("La boleta")
    alcance = await alcance_boletas(session, principal)
    if alcance is not None and not incluye(alcance, boleta.registro_id, boleta.periodo):
        raise _not_found("La boleta")
    return boleta


@dataclass(frozen=True)
class Verificacion:
    boleta: Boleta
    registro_numero: int
    integra: bool


async def verificar(session: AsyncSession, codigo: str) -> Verificacion:
    """Verificación pública por el código impreso (QR). No requiere sesión."""
    boleta = await session.scalar(
        select(Boleta).where(Boleta.codigo_verificacion == codigo.strip().upper())
    )
    if boleta is None:
        raise _not_found("La boleta")
    registro = await session.get(RegistroNotarial, boleta.registro_id)
    assert registro is not None  # noqa: S101 - FK RESTRICT
    integra = secrets.compare_digest(
        checksum_boleta(boleta, registro.numero_registro), boleta.checksum_sha256
    )
    return Verificacion(boleta, registro.numero_registro, integra)


async def datos_pdf(session: AsyncSession, boleta: Boleta) -> DatosBoleta:
    registro = await session.get(RegistroNotarial, boleta.registro_id)
    ddjj = await session.get(DeclaracionJurada, boleta.ddjj_id)
    assert registro is not None and ddjj is not None  # noqa: S101 - FK RESTRICT
    escribanos: dict[uuid.UUID, EscribanoBoleta] = {}
    if boleta.escribano_id is not None:
        # Boleta de un escribano: es la suya (cargo congelado al emitir).
        propio = await session.get(Escribano, boleta.escribano_id)
        assert propio is not None and boleta.cargo is not None  # noqa: S101 - FK RESTRICT
        escribanos[propio.id] = EscribanoBoleta(
            nombre_escribano(propio), CARGO_TEXTO.get(boleta.cargo, boleta.cargo)
        )
    else:
        # Boleta del registro (anterior a las boletas por notario): todo el equipo.
        for c in await cargos_en_periodo(session, boleta.registro_id, boleta.periodo):
            escribanos.setdefault(
                c.escribano_id,
                EscribanoBoleta(nombre_escribano(c.escribano), CARGO_TEXTO.get(c.cargo, c.cargo)),
            )
    return DatosBoleta(
        boleta=boleta,
        registro_numero=registro.numero_registro,
        numero_rectificativa=ddjj.numero_rectificativa,
        escribanos=list(escribanos.values()),
    )
