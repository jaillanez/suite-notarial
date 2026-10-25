"""Declaraciones juradas mensuales y boletas (Módulo 5).

Acceso por registro notarial:
- Un escribano opera las DDJJ de los registros donde tiene un cargo vigente (`ddjj:create_own`,
  que exige matrícula activa) y consulta las de los registros donde tuvo cargo (`ddjj:read_own`).
- El personal de la Caja consulta todo (`ddjj:read_all`) y puede cargar y presentar en nombre
  del registro (`ddjj:approve`), como hoy en el sistema actual.

El cálculo se hace siempre en el servidor (`liquidacion.liquidar`) con las vigencias del primer
día del período; al presentar se congelan el aporte y la vigencia de cada acto y la boleta guarda
las vigencias del mínimo, el aporte médico y la mora (SNAP).
"""

import base64
import calendar
import hashlib
import json
import secrets
import uuid
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
from app.common.pagination import PageParams
from app.core.errors import ProblemError
from app.modules.ddjj.catalog import (
    CONCEPTO_MEDICO,
    CONCEPTO_MINIMO,
    CONCEPTO_MORA,
    CONCEPTO_POR_CATEGORIA,
    CategoriaActo,
    EstadoBoleta,
    EstadoDDJJ,
)
from app.modules.ddjj.liquidacion import (
    ActoALiquidar,
    Liquidacion,
    LiquidacionError,
    liquidar,
    totalizar,
)
from app.modules.ddjj.models import Acto, Boleta, DeclaracionJurada, Vencimiento
from app.modules.ddjj.pdf import DatosBoleta, EscribanoBoleta
from app.modules.ddjj.schemas import ActoIn, DeclaracionIn, PresentarIn
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal
from app.modules.iam.models import User
from app.modules.padron.catalog import Cargo, EstadoRegistro
from app.modules.padron.models import Adscripcion, Escribano, RegistroNotarial
from app.modules.pagos.catalog import EstadoComprobante
from app.modules.pagos.models import Comprobante
from app.modules.parametros import service as parametros
from app.modules.parametros.models import Vigencia
from app.modules.parametros.motor import VigenciaSnapshot

# Plazo máximo entre la emisión de una boleta y la fecha hasta la que se puede pagar.
# TODO(negocio): confirmar con la Caja el plazo de validez de una boleta.
MAX_DIAS_VALIDEZ_BOLETA = 60
CARGO_TEXTO = {
    Cargo.TITULAR.value: "Titular",
    Cargo.ADSCRIPTO.value: "Adscripto",
    Cargo.SUPLENTE_INTERINO.value: "A cargo",
}
# Cargos que tributan el aporte médico asistencial (los "a cargo" no: ver liquidacion.py).
CARGOS_CON_APORTE_MEDICO = (Cargo.TITULAR.value, Cargo.ADSCRIPTO.value)


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
    return set((await session.scalars(stmt)).all())


def _es_staff_lectura(principal: Principal) -> bool:
    return Perm.DDJJ_READ_ALL.value in principal.permissions


def _es_staff_carga(principal: Principal) -> bool:
    return Perm.DDJJ_APPROVE.value in principal.permissions


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
    return [
        Alcance(
            c.registro_id,
            periodo_de(c.fecha_desde),
            periodo_de(c.fecha_hasta) if c.fecha_hasta else None,
        )
        for c in cargos.unique()
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


async def cargos_en_periodo(
    session: AsyncSession, registro_id: uuid.UUID, periodo: str
) -> list[Adscripcion]:
    """Cargos del registro que estuvieron vigentes en algún día del período."""
    desde, hasta = rango_periodo(periodo)
    result = await session.execute(
        select(Adscripcion)
        .where(
            Adscripcion.registro_id == registro_id,
            Adscripcion.fecha_desde <= hasta,
            or_(Adscripcion.fecha_hasta.is_(None), Adscripcion.fecha_hasta >= desde),
        )
        .order_by(Adscripcion.cargo.desc(), Adscripcion.fecha_desde)
    )
    return list(result.unique().scalars())


def cantidad_aportes_medicos(cargos: list[Adscripcion]) -> int:
    """Un aporte médico por escribano titular o adscripto del registro en el período.

    TODO(negocio): confirmar con la Caja (ver liquidacion.py).
    """
    return len({c.escribano_id for c in cargos if c.cargo in CARGOS_CON_APORTE_MEDICO})


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
    "folio",
    "fecha_acto",
    "naturaleza",
    "categoria",
    "base_imponible",
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
) -> Acto:
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
    cargo = await session.scalar(
        select(Adscripcion)
        .where(
            Adscripcion.registro_id == ddjj.registro_id,
            Adscripcion.escribano_id == data.escribano_id,
            Adscripcion.fecha_desde <= data.fecha_acto,
            or_(Adscripcion.fecha_hasta.is_(None), Adscripcion.fecha_hasta >= data.fecha_acto),
        )
        .order_by(Adscripcion.fecha_desde.desc())
    )
    if cargo is None:
        raise _invalid("El escribano no tenía cargo en este registro a la fecha del acto.")
    item = Acto(
        id=uuid.uuid4(),
        ddjj_id=ddjj.id,
        escribano_id=data.escribano_id,
        cargo=cargo.cargo,
        tipo_protocolo=data.tipo_protocolo.value,
        numero_escritura=data.numero_escritura,
        folio=data.folio,
        fecha_acto=data.fecha_acto,
        naturaleza=data.naturaleza,
        categoria=data.categoria.value,
        base_imponible=data.base_imponible,
        created_by_user_id=principal.user.id,
    )
    session.add(item)
    record_audit(
        session,
        ctx,
        AuditEvent.DDJJ_ACTO_AGREGADO,
        actor_user_id=principal.user.id,
        new_value=_acto_values(item),
        details={"ddjj_id": str(ddjj.id), "acto_id": str(item.id)},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict(
            f"La escritura N° {data.numero_escritura} del protocolo "
            f"{data.tipo_protocolo.value.lower()} ya está declarada en esta DDJJ."
        ) from exc
    result = await session.execute(select(Acto).where(Acto.id == item.id))
    return result.unique().scalar_one()


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
    liquidacion: Liquidacion
    vencimiento: date
    fecha_pago: date
    minimo: VigenciaSnapshot
    medico: VigenciaSnapshot
    mora: VigenciaSnapshot | None
    usa_valores_de_ejemplo: bool


async def _hay_ejemplos(session: AsyncSession, ids: set[uuid.UUID]) -> bool:
    if not ids:
        return False
    return bool(
        await session.scalar(
            select(func.count()).where(Vigencia.id.in_(ids), Vigencia.es_ejemplo.is_(True))
        )
    )


async def _mora_si_corresponde(
    session: AsyncSession, vencimiento: date, fecha_pago: date
) -> VigenciaSnapshot | None:
    # La tasa que rige es la vigente al vencimiento. TODO(negocio): confirmar con la Caja si
    # un cambio de tasa durante la mora se aplica por tramos.
    if fecha_pago <= vencimiento:
        return None
    return await parametros.get_vigencia(session, CONCEPTO_MORA, vencimiento)


def _liquidar(
    actos: list[tuple[ActoALiquidar, VigenciaSnapshot | None]],
    *,
    minimo: VigenciaSnapshot,
    medico: VigenciaSnapshot,
    cantidad_medicos: int,
    vencimiento: date,
    fecha_pago: date,
    mora: VigenciaSnapshot | None,
) -> Liquidacion:
    try:
        return liquidar(
            actos,
            minimo=minimo,
            medico=medico,
            cantidad_aportes_medicos=cantidad_medicos,
            vencimiento=vencimiento,
            fecha_pago=fecha_pago,
            mora=mora,
        )
    except LiquidacionError as exc:
        raise _invalid(str(exc)) from exc


async def preliquidar(
    session: AsyncSession, ddjj: DeclaracionJurada, actos: list[Acto], fecha_pago: date
) -> Preliquidacion:
    """Liquidación de un borrador con los parámetros vigentes al primer día del período."""
    inicio, _ = rango_periodo(ddjj.periodo)
    vencimiento = await _vencimiento_requerido(session, ddjj.periodo)
    por_concepto: dict[str, VigenciaSnapshot] = {}
    a_liquidar: list[tuple[ActoALiquidar, VigenciaSnapshot | None]] = []
    for acto in actos:
        categoria = CategoriaActo(acto.categoria)
        codigo = CONCEPTO_POR_CATEGORIA[categoria]
        vigencia = None
        if codigo is not None:
            if codigo not in por_concepto:
                por_concepto[codigo] = await parametros.get_vigencia(session, codigo, inicio)
            vigencia = por_concepto[codigo]
        a_liquidar.append((ActoALiquidar(categoria, acto.base_imponible), vigencia))
    minimo = await parametros.get_vigencia(session, CONCEPTO_MINIMO, inicio)
    medico = await parametros.get_vigencia(session, CONCEPTO_MEDICO, inicio)
    mora = await _mora_si_corresponde(session, vencimiento, fecha_pago)
    cargos = await cargos_en_periodo(session, ddjj.registro_id, ddjj.periodo)
    liquidacion = _liquidar(
        a_liquidar,
        minimo=minimo,
        medico=medico,
        cantidad_medicos=cantidad_aportes_medicos(cargos),
        vencimiento=vencimiento,
        fecha_pago=fecha_pago,
        mora=mora,
    )
    usadas = {v.vigencia_id for v in por_concepto.values()} | {minimo.vigencia_id}
    usadas |= {medico.vigencia_id} | ({mora.vigencia_id} if mora else set())
    return Preliquidacion(
        liquidacion=liquidacion,
        vencimiento=vencimiento,
        fecha_pago=fecha_pago,
        minimo=minimo,
        medico=medico,
        mora=mora,
        usa_valores_de_ejemplo=await _hay_ejemplos(session, usadas),
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
    vigencia_mora_id: uuid.UUID | None,
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
        vigencia_mora_id=vigencia_mora_id,
        emitida_por_user_id=actor.id,
        checksum_sha256="",
    )
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
        },
    )
    return boleta


async def _boleta_pendiente(session: AsyncSession, ddjj_id: uuid.UUID) -> Boleta | None:
    return await session.scalar(
        select(Boleta)
        .where(Boleta.ddjj_id == ddjj_id, Boleta.estado == EstadoBoleta.PENDIENTE.value)
        .with_for_update()
    )


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
) -> Boleta:
    """Congela la liquidación de cada acto y emite la boleta en la misma transacción."""
    ddjj = await get_declaracion(session, principal, ddjj_id, lock=True)
    await _exigir_operacion(session, principal, ddjj.registro_id)
    _exigir_borrador(ddjj)
    if ddjj.periodo >= periodo_de(today_local()):
        raise _invalid("La declaración jurada se presenta una vez terminado el período.")
    _validar_fecha_pago(data.fecha_pago)
    actos = await list_actos(session, ddjj.id)
    pre = await preliquidar(session, ddjj, actos, data.fecha_pago)
    for acto, aporte in zip(actos, pre.liquidacion.aportes, strict=True):
        acto.aporte = aporte.aporte
        acto.vigencia_id = aporte.vigencia.vigencia_id if aporte.vigencia else None
    await session.flush()
    ddjj.estado = EstadoDDJJ.PRESENTADA.value
    ddjj.fecha_presentacion = datetime.now(UTC)
    ddjj.presentada_por_user_id = principal.user.id
    ddjj.total_protocolos = pre.liquidacion.total_protocolos
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
            "total_protocolos": f"{pre.liquidacion.total_protocolos:.2f}",
        },
        details={"ddjj_id": str(ddjj.id), "periodo": ddjj.periodo},
    )
    boleta = await _crear_boleta(
        session,
        ctx,
        principal.user,
        ddjj,
        liquidacion=pre.liquidacion,
        vencimiento=pre.vencimiento,
        fecha_pago=data.fecha_pago,
        vigencia_minimo_id=pre.minimo.vigencia_id,
        vigencia_medico_id=pre.medico.vigencia_id,
        vigencia_mora_id=pre.mora.vigencia_id if pre.mora else None,
    )
    await session.commit()
    return boleta


async def _exigir_sin_comprobante_en_revision(session: AsyncSession, ddjj_id: uuid.UUID) -> None:
    """Mientras Tesorería revisa un pago, la boleta no se anula (regla PAGO)."""
    en_revision = await session.scalar(
        select(func.count())
        .select_from(Comprobante)
        .join(Boleta, Boleta.id == Comprobante.boleta_id)
        .where(
            Boleta.ddjj_id == ddjj_id,
            Comprobante.estado == EstadoComprobante.PENDIENTE_REVISION.value,
        )
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
) -> Boleta:
    """Nueva boleta de una DDJJ presentada para otra fecha de pago (recalcula solo la mora).

    Los importes de protocolo, mínimo y aporte médico salen de la primera boleta (SNAP): un
    cambio posterior de parámetros no los altera. La boleta pendiente anterior se anula.
    """
    ddjj = await get_declaracion(session, principal, ddjj_id, lock=True)
    await _exigir_operacion(session, principal, ddjj.registro_id)
    if ddjj.estado != EstadoDDJJ.PRESENTADA.value:
        raise _conflict("Solo se emiten boletas de una declaración jurada presentada.")
    _validar_fecha_pago(fecha_pago)
    await _exigir_sin_comprobante_en_revision(session, ddjj.id)
    if await session.scalar(
        select(func.count()).where(
            Boleta.ddjj_id == ddjj.id, Boleta.estado == EstadoBoleta.PAGADA.value
        )
    ):
        raise _conflict("La declaración jurada ya está paga.")
    base = await session.scalar(
        select(Boleta).where(Boleta.ddjj_id == ddjj.id).order_by(Boleta.numero).limit(1)
    )
    if base is None:
        raise _conflict("La declaración jurada no tiene boleta original.")
    mora = await _mora_si_corresponde(session, base.fecha_vencimiento, fecha_pago)
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
    pendiente = await _boleta_pendiente(session, ddjj.id)
    if pendiente is not None:
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
        vigencia_mora_id=mora.vigencia_id if mora else None,
    )
    await session.commit()
    return boleta


async def rectificar(
    session: AsyncSession, ctx: RequestContext, principal: Principal, ddjj_id: uuid.UUID
) -> DeclaracionJurada:
    """Abre la rectificativa de una DDJJ presentada, con una copia editable de sus actos.

    La original pasa a RECTIFICADA (queda intacta como antecedente) y su boleta pendiente se
    anula. TODO(negocio): rectificar una DDJJ ya paga requiere definir cómo se imputa lo pagado.
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
            "La declaración jurada ya está paga: la rectificación con pago a cuenta todavía no "
            "está disponible."
        )
    await _exigir_sin_comprobante_en_revision(session, original.id)
    pendiente = await _boleta_pendiente(session, original.id)
    if pendiente is not None:
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
                folio=acto.folio,
                fecha_acto=acto.fecha_acto,
                naturaleza=acto.naturaleza,
                categoria=acto.categoria,
                base_imponible=acto.base_imponible,
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
    cargos = await cargos_en_periodo(session, boleta.registro_id, boleta.periodo)
    escribanos: dict[uuid.UUID, EscribanoBoleta] = {}
    for c in cargos:
        persona = c.escribano.persona
        escribanos.setdefault(
            c.escribano_id,
            EscribanoBoleta(
                f"{persona.apellido.upper()}, {persona.nombre}", CARGO_TEXTO.get(c.cargo, c.cargo)
            ),
        )
    return DatosBoleta(
        boleta=boleta,
        registro_numero=registro.numero_registro,
        numero_rectificativa=ddjj.numero_rectificativa,
        escribanos=list(escribanos.values()),
    )
