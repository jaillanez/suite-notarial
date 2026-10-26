"""Corridas de migración, habilitación de la carga definitiva y conformidades.

- Simulacro: valida, carga y cuadra dentro de una transacción que se revierte. Quedan la
  corrida, su informe y sus observaciones.
- Definitiva: igual, pero confirma. Solo si la homologación no es de ejemplo, hay al menos
  `MIGRACION_SIMULACROS_MINIMOS` simulacros que cuadraron y el último simulacro del mismo lote
  (misma huella) cuadró y tiene la conformidad de Tesorería y de Caja. Una sola por base.
- La ejecución es por consola (operador con `migracion:ejecutar`); la Suite muestra corridas,
  cuadratura y observaciones, y registra las conformidades.
"""

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.audit import AuditEvent, RequestContext, record_audit
from app.core.config import get_settings
from app.core.errors import ProblemError
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal
from app.modules.iam.models import User
from app.modules.migracion import carga, cuadratura, formato, homologacion
from app.modules.migracion.catalog import (
    NOMBRE_AREA,
    ROL_DEL_AREA,
    AreaConformidad,
    EstadoCorrida,
    ModoCorrida,
)
from app.modules.migracion.models import Conformidad, Corrida, ObservacionMigracion
from app.modules.migracion.validacion import Existentes, Staging, validar
from app.modules.padron.models import Escribano, Persona, RegistroNotarial

CONSOLA = RequestContext(
    ip_address=None, user_agent="cli", correlation_id=None, path="cli:migracion"
)


class MigracionError(Exception):
    """La corrida no se puede hacer (habilitación, operador, lote): mensaje para la consola."""


@dataclass(frozen=True)
class Resultado:
    corrida_id: uuid.UUID
    estado: EstadoCorrida
    cuadra: bool
    bloqueantes: int
    advertencias: int
    informe: dict[str, Any]


def _ahora() -> datetime:
    return datetime.now(UTC)


async def _operador(session: AsyncSession, email: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        raise MigracionError(f"No hay un usuario activo con el correo {email}.")
    if Perm.MIGRACION_EJECUTAR.value not in user.permission_codes:
        raise MigracionError("El operador no tiene el permiso migracion:ejecutar.")
    return user


async def _existentes(session: AsyncSession) -> Existentes:
    return Existentes(
        cuits=frozenset((await session.scalars(select(Persona.cuit))).all()),
        matriculas=frozenset((await session.scalars(select(Escribano.matricula_numero))).all()),
        registros=frozenset(
            (await session.scalars(select(RegistroNotarial.numero_registro))).all()
        ),
    )


async def habilitacion_definitiva(
    session: AsyncSession, huella: str, homologacion_ejemplo: bool
) -> list[str]:
    """Motivos que impiden la carga definitiva de este lote (vacío: habilitada)."""
    motivos = []
    if homologacion_ejemplo:
        motivos.append(
            "La tabla de homologación es de ejemplo: la Caja tiene que aprobar la definitiva."
        )
    minimos = get_settings().MIGRACION_SIMULACROS_MINIMOS
    cuadrados = await session.scalar(
        select(func.count()).where(
            Corrida.modo == ModoCorrida.SIMULACRO.value,
            Corrida.estado == EstadoCorrida.SIMULADA.value,
            Corrida.cuadra.is_(True),
        )
    )
    if (cuadrados or 0) < minimos:
        motivos.append(f"Hacen falta {minimos} simulacros que cuadren (hay {cuadrados or 0}).")
    ultimo = await session.scalar(
        select(Corrida)
        .where(Corrida.modo == ModoCorrida.SIMULACRO.value, Corrida.huella_lote == huella)
        # created_at es la hora de la transacción: el cierre desempata corridas simultáneas.
        .order_by(Corrida.created_at.desc(), Corrida.finalizada_en.desc().nulls_first())
        .limit(1)
    )
    if ultimo is None:
        motivos.append("No hay un simulacro de este mismo lote.")
    else:
        if not (ultimo.estado == EstadoCorrida.SIMULADA.value and ultimo.cuadra):
            motivos.append("El último simulacro de este lote no cuadró.")
        areas = set(
            (
                await session.scalars(
                    select(Conformidad.area).where(Conformidad.corrida_id == ultimo.id)
                )
            ).all()
        )
        faltan = [a for a in AreaConformidad if a.value not in areas]
        if faltan:
            motivos.append(
                "Falta la conformidad de "
                + " y ".join(NOMBRE_AREA[a] for a in faltan)
                + " sobre el último simulacro de este lote."
            )
    ya = await session.scalar(
        select(func.count()).where(
            Corrida.modo == ModoCorrida.DEFINITIVA.value,
            Corrida.estado.in_([EstadoCorrida.CARGADA.value, EstadoCorrida.EN_CURSO.value]),
        )
    )
    if ya:
        motivos.append("La base ya tiene una carga definitiva.")
    return motivos


def _observaciones(corrida_id: uuid.UUID, st: Staging) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.uuid4(),
            "corrida_id": corrida_id,
            "entidad": o.entidad.value,
            "fila": o.fila,
            "codigo_legado": o.codigo_legado[:100],
            "codigo": o.codigo,
            "severidad": o.severidad.value,
            "mensaje": o.mensaje,
        }
        for o in st.observaciones
    ]


async def _finalizar(
    session: AsyncSession,
    corrida: Corrida,
    estado: EstadoCorrida,
    st: Staging,
    informe: dict[str, Any],
    duracion_ms: int,
) -> None:
    corrida.estado = estado.value
    corrida.finalizada_en = _ahora()
    corrida.cuadra = bool(informe["cuadra"])
    corrida.bloqueantes = int(informe["bloqueantes"])
    corrida.advertencias = int(informe["advertencias"])
    corrida.informe = informe
    corrida.duracion_ms = duracion_ms
    observaciones = _observaciones(corrida.id, st)
    for i in range(0, len(observaciones), carga.LOTE_INSERT):
        await session.execute(
            insert(ObservacionMigracion), observaciones[i : i + carga.LOTE_INSERT]
        )
    record_audit(
        session,
        CONSOLA,
        AuditEvent.MIGRACION_FINALIZADA,
        actor_user_id=corrida.operador_user_id,
        details={
            "corrida_id": str(corrida.id),
            "modo": corrida.modo,
            "estado": estado.value,
            "cuadra": corrida.cuadra,
            "bloqueantes": corrida.bloqueantes,
            "advertencias": corrida.advertencias,
        },
    )


async def correr(
    directorio: Path,
    modo: ModoCorrida,
    operador_email: str,
    *,
    homologacion_ruta: Path | None = None,
    maker: async_sessionmaker[AsyncSession],
) -> Resultado:
    lote = formato.leer_lote(directorio)
    hom = homologacion.cargar(homologacion_ruta)

    async with maker() as session:
        operador = await _operador(session, operador_email)
        if modo is ModoCorrida.DEFINITIVA:
            motivos = await habilitacion_definitiva(session, lote.huella, hom.es_ejemplo)
            if motivos:
                raise MigracionError("Carga definitiva no habilitada:\n- " + "\n- ".join(motivos))
        corrida = Corrida(
            id=uuid.uuid4(),
            modo=modo.value,
            estado=EstadoCorrida.EN_CURSO.value,
            huella_lote=lote.huella,
            version_formato=formato.VERSION_FORMATO,
            homologacion=hom.origen,
            homologacion_ejemplo=hom.es_ejemplo,
            operador_user_id=operador.id,
        )
        session.add(corrida)
        record_audit(
            session,
            CONSOLA,
            AuditEvent.MIGRACION_INICIADA,
            actor_user_id=operador.id,
            details={"corrida_id": str(corrida.id), "modo": modo.value, "huella": lote.huella},
        )
        await session.commit()
        corrida_id, operador_id = corrida.id, operador.id

    inicio = time.perf_counter_ns()
    try:
        async with maker() as session:
            st = validar(lote, hom, await _existentes(session))
            cargado = await carga.cargar(session, st, corrida_id, operador_id)
            informe = await cuadratura.calcular(session, lote, st, cargado, corrida_id)
            duracion = (time.perf_counter_ns() - inicio) // 1_000_000
            if modo is ModoCorrida.DEFINITIVA:
                # Carga, informe y observaciones se confirman juntos.
                corrida = await session.get_one(Corrida, corrida_id)
                await _finalizar(session, corrida, EstadoCorrida.CARGADA, st, informe, duracion)
                await session.commit()
            else:
                await session.rollback()
        if modo is ModoCorrida.SIMULACRO:
            async with maker() as session:
                corrida = await session.get_one(Corrida, corrida_id)
                await _finalizar(session, corrida, EstadoCorrida.SIMULADA, st, informe, duracion)
                await session.commit()
    except Exception as exc:
        async with maker() as session:
            corrida = await session.get_one(Corrida, corrida_id)
            corrida.estado = EstadoCorrida.FALLIDA.value
            corrida.finalizada_en = _ahora()
            corrida.error = f"{type(exc).__name__}: {exc}"[:2000]
            record_audit(
                session,
                CONSOLA,
                AuditEvent.MIGRACION_FALLIDA,
                actor_user_id=operador_id,
                details={"corrida_id": str(corrida_id), "error": type(exc).__name__},
            )
            await session.commit()
        raise
    return Resultado(
        corrida_id,
        EstadoCorrida.CARGADA if modo is ModoCorrida.DEFINITIVA else EstadoCorrida.SIMULADA,
        bool(informe["cuadra"]),
        int(informe["bloqueantes"]),
        int(informe["advertencias"]),
        informe,
    )


# --------------------------------------------------------------------------- consulta (API)


async def listar(session: AsyncSession) -> Sequence[Corrida]:
    return (await session.scalars(select(Corrida).order_by(Corrida.created_at.desc()))).all()


async def get_corrida(session: AsyncSession, corrida_id: uuid.UUID) -> Corrida:
    corrida = await session.get(Corrida, corrida_id)
    if corrida is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "La corrida no existe.")
    return corrida


async def observaciones(
    session: AsyncSession,
    corrida_id: uuid.UUID,
    *,
    severidad: str | None,
    entidad: str | None,
    page: int,
    page_size: int,
) -> tuple[Sequence[ObservacionMigracion], int]:
    filtros = [ObservacionMigracion.corrida_id == corrida_id]
    if severidad:
        filtros.append(ObservacionMigracion.severidad == severidad)
    if entidad:
        filtros.append(ObservacionMigracion.entidad == entidad)
    total = await session.scalar(select(func.count()).where(*filtros))
    filas = await session.scalars(
        select(ObservacionMigracion)
        .where(*filtros)
        .order_by(
            ObservacionMigracion.severidad.desc(),
            ObservacionMigracion.entidad,
            ObservacionMigracion.fila,
            ObservacionMigracion.id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return filas.all(), int(total or 0)


async def conformidades(session: AsyncSession, corrida_id: uuid.UUID) -> Sequence[Conformidad]:
    return (
        await session.scalars(
            select(Conformidad)
            .where(Conformidad.corrida_id == corrida_id)
            .order_by(Conformidad.firmada_en)
        )
    ).all()


async def conformar(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    corrida_id: uuid.UUID,
    area: AreaConformidad,
    observaciones: str | None,
) -> Conformidad:
    corrida = await session.scalar(
        select(Corrida).where(Corrida.id == corrida_id).with_for_update()
    )
    if corrida is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "La corrida no existe.")
    if ROL_DEL_AREA[area] not in principal.user.role_codes:
        raise ProblemError(
            HTTPStatus.FORBIDDEN, f"Solo alguien de {NOMBRE_AREA[area]} firma por esa área."
        )
    if (
        corrida.modo != ModoCorrida.SIMULACRO.value
        or corrida.estado != EstadoCorrida.SIMULADA.value
    ):
        raise ProblemError(HTTPStatus.CONFLICT, "Solo se da conformidad a un simulacro terminado.")
    if not corrida.cuadra:
        raise ProblemError(
            HTTPStatus.CONFLICT, "El simulacro no cuadró: no se puede dar conformidad."
        )
    previas = await conformidades(session, corrida_id)
    if any(c.area == area.value for c in previas):
        raise ProblemError(HTTPStatus.CONFLICT, "Esa área ya firmó este simulacro.")
    if any(c.user_id == principal.user.id for c in previas):
        raise ProblemError(
            HTTPStatus.CONFLICT, "Ya firmaste este simulacro: la otra área firma otra persona."
        )
    conformidad = Conformidad(
        id=uuid.uuid4(),
        corrida_id=corrida_id,
        area=area.value,
        user_id=principal.user.id,
        observaciones=observaciones,
        firmada_en=_ahora(),
    )
    session.add(conformidad)
    record_audit(
        session,
        ctx,
        AuditEvent.MIGRACION_CONFORMIDAD,
        actor_user_id=principal.user.id,
        details={"corrida_id": str(corrida_id), "area": area.value, "huella": corrida.huella_lote},
    )
    await session.commit()
    return conformidad
