"""Aportes y puntos previsionales (reglamentación de la Ley 7231).

- La carga de la planilla histórica es idempotente: lo que ya está y coincide se saltea; lo que
  ya está y difiere NO se sobreescribe (regla INM): se informa para que la Caja decida.
- Cada nombre de la planilla se vincula con un escribano del padrón (ver `vinculacion`); lo que
  no se puede vincular con seguridad queda en «Puntos sin vincular» para hacerlo a mano.
- El cálculo de puntos de ejercicios nuevos NO está implementado: falta la regla oficial de la
  Caja. TODO(negocio): ver docs/previsional-puntos.md.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from http import HTTPStatus
from typing import Any, NoReturn

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.common.pagination import PageParams
from app.core.errors import ProblemError
from app.modules.iam.catalog import Perm
from app.modules.iam.models import User
from app.modules.padron.models import Escribano, Persona
from app.modules.previsional.catalog import MOTIVO_SIN_REGLA, EstadoVinculo, Vinculacion
from app.modules.previsional.models import Ejercicio, PuntosAfiliado
from app.modules.previsional.planilla import Planilla
from app.modules.previsional.vinculacion import Candidato, Vinculador

CERO = Decimal("0.00")
TIPO_REGLA_PENDIENTE = "urn:suite-notarial:previsional:regla-pendiente"


class CargaError(Exception):
    """La carga no se puede hacer (operador, planilla): mensaje para la consola."""


# --------------------------------------------------------------------------- carga


@dataclass(frozen=True)
class Diferencia:
    """Un dato ya cargado que no coincide con la planilla (no se sobreescribe)."""

    anio: int
    fila: int | None
    campos: dict[str, tuple[str, str]]  # campo → (cargado, planilla)


@dataclass
class ResultadoVinculacion:
    exactas: int = 0
    # (nombre de la planilla, escribano): para revisar.
    aproximadas: list[tuple[str, uuid.UUID]] = field(default_factory=list)
    # Ya vinculado en otros ejercicios: las filas nuevas siguen el mismo vínculo.
    heredadas: int = 0
    ambiguas: list[str] = field(default_factory=list)
    sin_vincular: list[str] = field(default_factory=list)
    filas_vinculadas: int = 0


@dataclass
class ResultadoCarga:
    ejercicios_nuevos: int = 0
    ejercicios_iguales: int = 0
    puntos_nuevos: int = 0
    puntos_iguales: int = 0
    diferencias: list[Diferencia] = field(default_factory=list)
    vinculacion: ResultadoVinculacion = field(default_factory=ResultadoVinculacion)


async def operador(session: AsyncSession, email: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        raise CargaError(f"No hay un usuario activo con el correo {email}.")
    if Perm.PUNTOS_MANAGE.value not in user.permission_codes:
        raise CargaError("El operador no tiene el permiso puntos:manage.")
    return user


def _texto(valor: Any) -> str:
    return valor.isoformat() if isinstance(valor, date) else str(valor)


async def cargar(
    session: AsyncSession,
    planilla: Planilla,
    actor: User,
    origen: str,
    ctx: RequestContext,
) -> ResultadoCarga:
    """Guarda ejercicios y puntos que falten y vincula lo que se pueda. No confirma."""
    resultado = ResultadoCarga()
    existentes = {
        e.anio: e
        for e in (
            await session.scalars(
                select(Ejercicio).where(Ejercicio.anio.in_([e.anio for e in planilla.ejercicios]))
            )
        ).all()
    }
    ids: dict[int, uuid.UUID] = {}
    for leido in planilla.ejercicios:
        actual = existentes.get(leido.anio)
        if actual is None:
            nuevo = Ejercicio(
                id=uuid.uuid4(),
                anio=leido.anio,
                fecha_inicio=leido.fecha_inicio,
                fecha_cierre=leido.fecha_cierre,
                total_aportes=leido.total_aportes,
                cantidad_afiliados=leido.cantidad_afiliados,
                aporte_medio=leido.aporte_medio,
                origen=origen,
                created_by_user_id=actor.id,
            )
            session.add(nuevo)
            ids[leido.anio] = nuevo.id
            resultado.ejercicios_nuevos += 1
            continue
        ids[leido.anio] = actual.id
        campos = {
            campo: (_texto(getattr(actual, campo)), _texto(getattr(leido, campo)))
            for campo in (
                "fecha_inicio",
                "fecha_cierre",
                "total_aportes",
                "cantidad_afiliados",
                "aporte_medio",
            )
            if getattr(actual, campo) != getattr(leido, campo)
        }
        if campos:
            resultado.diferencias.append(Diferencia(leido.anio, None, campos))
        else:
            resultado.ejercicios_iguales += 1
    await session.flush()

    cargados = {
        (p.ejercicio_id, p.nombre_origen): p
        for p in (
            await session.scalars(
                select(PuntosAfiliado).where(PuntosAfiliado.ejercicio_id.in_(list(ids.values())))
            )
        ).all()
    }
    for leido_p in planilla.puntos:
        ejercicio_id = ids[leido_p.anio]
        previo = cargados.get((ejercicio_id, leido_p.nombre))
        if previo is None:
            session.add(
                PuntosAfiliado(
                    ejercicio_id=ejercicio_id,
                    nombre_origen=leido_p.nombre,
                    aportes=leido_p.aportes,
                    puntos=leido_p.puntos,
                    origen=origen,
                    fila_origen=leido_p.fila,
                    created_by_user_id=actor.id,
                )
            )
            resultado.puntos_nuevos += 1
            continue
        campos = {
            campo: (str(getattr(previo, campo)), str(getattr(leido_p, campo)))
            for campo in ("aportes", "puntos")
            if getattr(previo, campo) != getattr(leido_p, campo)
        }
        if campos:
            resultado.diferencias.append(Diferencia(leido_p.anio, leido_p.fila, campos))
        else:
            resultado.puntos_iguales += 1
    await session.flush()

    resultado.vinculacion = await revincular(session, actor)
    record_audit(
        session,
        ctx,
        AuditEvent.PUNTOS_PLANILLA_CARGADA,
        severity=Severity.WARNING if resultado.diferencias else Severity.INFO,
        actor_user_id=actor.id,
        details={
            "origen": origen,
            "ejercicios_nuevos": resultado.ejercicios_nuevos,
            "ejercicios_iguales": resultado.ejercicios_iguales,
            "puntos_nuevos": resultado.puntos_nuevos,
            "puntos_iguales": resultado.puntos_iguales,
            "diferencias": len(resultado.diferencias),
            "redondeos": len(planilla.redondeos),
            "vinculacion": _resumen_vinculacion(resultado.vinculacion),
        },
    )
    return resultado


def _resumen_vinculacion(v: ResultadoVinculacion) -> dict[str, int]:
    return {
        "exactas": v.exactas,
        "aproximadas": len(v.aproximadas),
        "heredadas": v.heredadas,
        "ambiguas": len(v.ambiguas),
        "sin_vincular": len(v.sin_vincular),
        "filas_vinculadas": v.filas_vinculadas,
    }


async def _candidatos(session: AsyncSession) -> list[Candidato]:
    filas = (
        await session.execute(
            select(Escribano.id, Persona.apellido, Persona.nombre).join(
                Persona, Persona.id == Escribano.persona_id
            )
        )
    ).all()
    return [Candidato(eid, f"{apellido} {nombre}") for eid, apellido, nombre in filas]


async def revincular(session: AsyncSession, actor: User) -> ResultadoVinculacion:
    """Intenta vincular las filas sin escribano (después de cargar el padrón, por ejemplo).

    Nunca toca una fila ya vinculada: los vínculos existentes solo cambian a mano.
    """
    resultado = ResultadoVinculacion()
    pendientes = list(
        (
            await session.scalars(
                select(PuntosAfiliado.nombre_origen)
                .where(PuntosAfiliado.escribano_id.is_(None))
                .distinct()
                .order_by(PuntosAfiliado.nombre_origen)
            )
        ).all()
    )
    if not pendientes:
        return resultado
    # Vínculos ya decididos para el mismo nombre (otros ejercicios): se respetan.
    previos: dict[str, dict[uuid.UUID, set[Vinculacion]]] = {}
    for nombre_previo, escribano_previo, forma_previa in (
        await session.execute(
            select(
                PuntosAfiliado.nombre_origen,
                PuntosAfiliado.escribano_id,
                PuntosAfiliado.vinculacion,
            )
            .where(
                PuntosAfiliado.nombre_origen.in_(pendientes),
                PuntosAfiliado.escribano_id.is_not(None),
            )
            .distinct()
        )
    ).all():
        if escribano_previo is not None and forma_previa is not None:
            previos.setdefault(nombre_previo, {}).setdefault(escribano_previo, set()).add(
                Vinculacion(forma_previa)
            )
    vinculador = Vinculador(await _candidatos(session))
    ahora = datetime.now(UTC)
    for nombre in pendientes:
        conocido = previos.get(nombre)
        escribano_id: uuid.UUID
        vinculacion: Vinculacion
        if conocido and len(conocido) == 1:
            escribano_id, formas = next(iter(conocido.items()))
            # La forma más firme decidida para ese nombre.
            vinculacion = next(
                v
                for v in (Vinculacion.MANUAL, Vinculacion.EXACTA, Vinculacion.APROXIMADA)
                if v in formas
            )
            resultado.heredadas += 1
        elif conocido:
            # El mismo nombre quedó vinculado a personas distintas: lo decide una persona.
            resultado.ambiguas.append(nombre)
            continue
        else:
            r = vinculador.vincular(nombre)
            if r.escribano_id is None or r.vinculacion is None:
                (resultado.ambiguas if r.ambiguo else resultado.sin_vincular).append(nombre)
                continue
            escribano_id, vinculacion = r.escribano_id, r.vinculacion
            if vinculacion is Vinculacion.APROXIMADA:
                resultado.aproximadas.append((nombre, escribano_id))
            else:
                resultado.exactas += 1
        filas = await session.execute(
            update(PuntosAfiliado)
            .where(
                PuntosAfiliado.nombre_origen == nombre,
                PuntosAfiliado.escribano_id.is_(None),
            )
            .values(
                escribano_id=escribano_id,
                vinculacion=vinculacion.value,
                vinculado_por_user_id=actor.id,
                vinculado_en=ahora,
            )
        )
        resultado.filas_vinculadas += int(getattr(filas, "rowcount", 0) or 0)
    await session.flush()
    return resultado


async def revincular_auditado(
    session: AsyncSession, actor: User, ctx: RequestContext
) -> ResultadoVinculacion:
    resultado = await revincular(session, actor)
    record_audit(
        session,
        ctx,
        AuditEvent.PUNTOS_REVINCULADOS,
        actor_user_id=actor.id,
        details=_resumen_vinculacion(resultado),
    )
    return resultado


# --------------------------------------------------------------------------- informe


@dataclass(frozen=True)
class FilaInforme:
    anio: int
    fecha_inicio: date
    fecha_cierre: date
    aportes: Decimal
    puntos: Decimal


@dataclass(frozen=True)
class OrigenInforme:
    nombre_origen: str
    vinculacion: Vinculacion
    ejercicios: int


@dataclass(frozen=True)
class Informe:
    escribano: Escribano
    filas: list[FilaInforme]
    origenes: list[OrigenInforme]
    # Textos de origen de las filas (p. ej. «Planilla histórica de la Caja …»).
    fuentes: list[str]
    total_aportes: Decimal
    total_puntos: Decimal


async def get_escribano(session: AsyncSession, escribano_id: uuid.UUID) -> Escribano:
    escribano = await session.get(Escribano, escribano_id)
    if escribano is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "El escribano no existe.")
    return escribano


async def escribano_de(session: AsyncSession, user: User) -> Escribano | None:
    return await session.scalar(select(Escribano).where(Escribano.user_id == user.id))


async def informe(session: AsyncSession, escribano: Escribano) -> Informe:
    """Aportes y puntos por ejercicio (si dos nombres del origen lo vinculan, se suman)."""
    filas = [
        FilaInforme(anio, inicio, cierre, Decimal(aportes), Decimal(puntos))
        for anio, inicio, cierre, aportes, puntos in (
            await session.execute(
                select(
                    Ejercicio.anio,
                    Ejercicio.fecha_inicio,
                    Ejercicio.fecha_cierre,
                    func.sum(PuntosAfiliado.aportes),
                    func.sum(PuntosAfiliado.puntos),
                )
                .join(Ejercicio, Ejercicio.id == PuntosAfiliado.ejercicio_id)
                .where(PuntosAfiliado.escribano_id == escribano.id)
                .group_by(Ejercicio.anio, Ejercicio.fecha_inicio, Ejercicio.fecha_cierre)
                .order_by(Ejercicio.anio)
            )
        ).all()
    ]
    origenes = [
        OrigenInforme(nombre, Vinculacion(vinculacion or Vinculacion.MANUAL), int(n))
        for nombre, vinculacion, n in (
            await session.execute(
                select(
                    PuntosAfiliado.nombre_origen,
                    PuntosAfiliado.vinculacion,
                    func.count(),
                )
                .where(PuntosAfiliado.escribano_id == escribano.id)
                .group_by(PuntosAfiliado.nombre_origen, PuntosAfiliado.vinculacion)
                .order_by(PuntosAfiliado.nombre_origen)
            )
        ).all()
    ]
    fuentes = list(
        (
            await session.scalars(
                select(PuntosAfiliado.origen)
                .where(PuntosAfiliado.escribano_id == escribano.id)
                .distinct()
                .order_by(PuntosAfiliado.origen)
            )
        ).all()
    )
    return Informe(
        escribano=escribano,
        filas=filas,
        origenes=origenes,
        fuentes=fuentes,
        total_aportes=sum((f.aportes for f in filas), CERO),
        total_puntos=sum((f.puntos for f in filas), Decimal("0.000000")),
    )


# --------------------------------------------------------------------------- sin vincular


@dataclass(frozen=True)
class NombreSinVincular:
    nombre_origen: str
    estado: EstadoVinculo
    ejercicios: int
    primer_anio: int
    ultimo_anio: int
    total_aportes: Decimal
    total_puntos: Decimal
    escribano: Escribano | None


def _sin_vincular_stmt(estado: EstadoVinculo, q: str | None) -> Select[*tuple[Any, ...]]:
    condicion = (
        PuntosAfiliado.escribano_id.is_(None)
        if estado is EstadoVinculo.SIN_VINCULAR
        else PuntosAfiliado.vinculacion == Vinculacion.APROXIMADA.value
    )
    stmt: Select[*tuple[Any, ...]] = (
        select(
            PuntosAfiliado.nombre_origen.label("nombre_origen"),
            PuntosAfiliado.escribano_id.label("escribano_id"),
            func.count().label("ejercicios"),
            func.min(Ejercicio.anio).label("primer_anio"),
            func.max(Ejercicio.anio).label("ultimo_anio"),
            func.sum(PuntosAfiliado.aportes).label("total_aportes"),
            func.sum(PuntosAfiliado.puntos).label("total_puntos"),
        )
        .join(Ejercicio, Ejercicio.id == PuntosAfiliado.ejercicio_id)
        .where(condicion)
        .group_by(PuntosAfiliado.nombre_origen, PuntosAfiliado.escribano_id)
    )
    if q and q.strip():
        stmt = stmt.where(PuntosAfiliado.nombre_origen.ilike(f"%{q.strip()}%"))
    return stmt


async def sin_vincular(
    session: AsyncSession, estado: EstadoVinculo, q: str | None, page: PageParams
) -> tuple[list[NombreSinVincular], int]:
    stmt = _sin_vincular_stmt(estado, q)
    total = int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    filas = (
        await session.execute(
            stmt.order_by(PuntosAfiliado.nombre_origen, PuntosAfiliado.escribano_id)
            .offset(page.offset)
            .limit(page.page_size)
        )
    ).all()
    escribanos = {
        e.id: e
        for e in (
            await session.scalars(
                select(Escribano).where(
                    Escribano.id.in_([f.escribano_id for f in filas if f.escribano_id])
                )
            )
        ).all()
    }
    return (
        [
            NombreSinVincular(
                nombre_origen=f.nombre_origen,
                estado=estado,
                ejercicios=int(f.ejercicios),
                primer_anio=int(f.primer_anio),
                ultimo_anio=int(f.ultimo_anio),
                total_aportes=Decimal(f.total_aportes),
                total_puntos=Decimal(f.total_puntos),
                escribano=escribanos.get(f.escribano_id) if f.escribano_id else None,
            )
            for f in filas
        ],
        total,
    )


async def vincular_manual(
    session: AsyncSession,
    nombre_origen: str,
    escribano_id: uuid.UUID,
    motivo: str | None,
    actor: User,
    ctx: RequestContext,
) -> int:
    """Vincula (o confirma) todas las filas de un nombre de la planilla con un escribano."""
    escribano = await get_escribano(session, escribano_id)
    filas = list(
        (
            await session.scalars(
                select(PuntosAfiliado)
                .where(PuntosAfiliado.nombre_origen == nombre_origen)
                .with_for_update()
            )
        ).all()
    )
    if not filas:
        raise ProblemError(HTTPStatus.NOT_FOUND, "No hay puntos cargados con ese nombre.")
    motivo = (motivo or "").strip() or None
    if all(
        f.escribano_id == escribano.id and f.vinculacion == Vinculacion.MANUAL.value for f in filas
    ):
        raise ProblemError(HTTPStatus.CONFLICT, "Esos puntos ya están vinculados a ese escribano.")
    reemplaza = any(
        f.escribano_id is not None
        and f.escribano_id != escribano.id
        and f.vinculacion != Vinculacion.APROXIMADA.value
        for f in filas
    )
    if reemplaza and motivo is None:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "Esos puntos ya estaban vinculados a otro escribano: indicá el motivo del cambio.",
        )
    anteriores = sorted(
        {(str(f.escribano_id), f.vinculacion) for f in filas if f.escribano_id is not None}
    )
    ahora = datetime.now(UTC)
    await session.execute(
        update(PuntosAfiliado)
        .where(PuntosAfiliado.nombre_origen == nombre_origen)
        .values(
            escribano_id=escribano.id,
            vinculacion=Vinculacion.MANUAL.value,
            vinculado_por_user_id=actor.id,
            vinculado_en=ahora,
        )
    )
    record_audit(
        session,
        ctx,
        AuditEvent.PUNTOS_VINCULADOS,
        severity=Severity.WARNING if reemplaza else Severity.INFO,
        actor_user_id=actor.id,
        target_user_id=escribano.user_id,
        old_value={"vinculos": [{"escribano_id": e, "vinculacion": v} for e, v in anteriores]},
        new_value={"escribano_id": str(escribano.id), "vinculacion": Vinculacion.MANUAL.value},
        details={"nombre_origen": nombre_origen, "filas": len(filas), "motivo": motivo},
    )
    await session.commit()
    return len(filas)


# --------------------------------------------------------------------------- crédito futuro


@dataclass(frozen=True)
class EstadoCalculo:
    habilitado: bool
    motivo: str


def estado_calculo() -> EstadoCalculo:
    """El crédito de puntos de un ejercicio nuevo queda deshabilitado hasta tener la regla."""
    return EstadoCalculo(habilitado=False, motivo=MOTIVO_SIN_REGLA)


async def calcular_puntos_ejercicio(session: AsyncSession, anio: int, actor: User) -> NoReturn:
    """Acreditaría los puntos de un ejercicio a partir de los aportes ingresados.

    TODO(negocio): no se implementa ninguna fórmula hasta que la Caja apruebe la regla oficial
    de cálculo (la relación observada en la planilla está documentada como hipótesis en
    docs/previsional-puntos.md). Cuando exista, este servicio: verifica que el ejercicio esté
    cerrado y sin puntos, toma los aportes confirmados por Tesorería, guarda el id de la
    regla usada (SNAP) y deja la acreditación pendiente de ratificación humana.
    """
    del session, anio, actor
    raise ProblemError(
        HTTPStatus.NOT_IMPLEMENTED,
        MOTIVO_SIN_REGLA,
        title="Cálculo de puntos no disponible",
        type_=TIPO_REGLA_PENDIENTE,
    )
