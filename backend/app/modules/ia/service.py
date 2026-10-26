"""Sugerencias asistidas y su ratificación humana (regla HIC).

- Analizar NO escribe nada fuera de `ia_sugerencias`: ni actos, ni personas, ni montos.
- Ratificar lo hace la misma persona que pidió la sugerencia, con los datos que revisó, y pasa
  por el servicio de siempre (`agregar_acto`, `create_escribano`): mismas validaciones, mismos
  permisos, misma auditoría. Sugerencia y registro de destino se confirman en un único commit.
- Toda sugerencia, ratificación y descarte queda en `audit_security_logs` (sin datos personales:
  ids, motor, confianza y campos corregidos).
"""

import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from http import HTTPStatus
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, record_audit
from app.common.dates import today_local
from app.core.config import get_settings
from app.core.errors import ProblemError
from app.modules.ddjj import service as ddjj_service
from app.modules.ddjj.catalog import EstadoDDJJ
from app.modules.ddjj.models import Acto, DeclaracionJurada
from app.modules.ddjj.schemas import ActoIn
from app.modules.ia import dni, lectura, minutas
from app.modules.ia.catalog import (
    MOTOR_DNI_VERSION,
    MOTOR_MINUTA,
    MOTOR_MINUTA_VERSION,
    EstadoSugerencia,
    TipoSugerencia,
)
from app.modules.ia.models import Sugerencia
from app.modules.ia.resultado import Resultado
from app.modules.iam.deps import Principal
from app.modules.padron import service as padron_service
from app.modules.padron.models import Escribano, Persona, RegistroNotarial
from app.modules.padron.schemas import EscribanoIn
from app.modules.pagos import storage
from app.modules.pagos.storage import ArchivoInvalidoError

MAX_TEXTO = minutas.MAX_CARACTERES


def _invalid(message: str, status: HTTPStatus = HTTPStatus.UNPROCESSABLE_ENTITY) -> ProblemError:
    return ProblemError(status, message)


def _archivo_error(exc: ArchivoInvalidoError) -> ProblemError:
    return ProblemError(HTTPStatus(exc.status), str(exc))


def _ocr_no_disponible() -> ProblemError:
    return ProblemError(
        HTTPStatus.SERVICE_UNAVAILABLE,
        "El reconocimiento de texto (OCR) no está disponible en este servidor: subí un PDF con "
        "texto o pegá el texto de la minuta.",
    )


def _ms(desde_ns: int) -> int:
    return (time.perf_counter_ns() - desde_ns) // 1_000_000


def _registrar(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    *,
    tipo: TipoSugerencia,
    motor: str,
    version: str,
    resultado: Resultado,
    entrada: dict[str, Any],
    tiempo_ms: int,
    ddjj_id: uuid.UUID | None = None,
) -> Sugerencia:
    sugerencia = Sugerencia(
        id=uuid.uuid4(),
        tipo=tipo.value,
        estado=EstadoSugerencia.SUGERIDO_POR_IA.value,
        motor=motor,
        motor_version=version,
        tiempo_ms=tiempo_ms,
        confianza=resultado.confianza(),
        entrada=entrada,
        salida=resultado.a_json(),
        ddjj_id=ddjj_id,
        solicitado_por_user_id=principal.user.id,
    )
    session.add(sugerencia)
    record_audit(
        session,
        ctx,
        AuditEvent.IA_SUGERENCIA_GENERADA,
        actor_user_id=principal.user.id,
        details={
            "sugerencia_id": str(sugerencia.id),
            "tipo": tipo.value,
            "motor": f"{motor} {version}",
            "confianza": str(sugerencia.confianza),
            "alertas": [a["codigo"] for a in sugerencia.salida["alertas"]],
            **({"ddjj_id": str(ddjj_id)} if ddjj_id else {}),
        },
    )
    return sugerencia


# --------------------------------------------------------------------------- minutas


async def _ddjj_operable(
    session: AsyncSession, principal: Principal, ddjj_id: uuid.UUID
) -> DeclaracionJurada:
    ddjj = await ddjj_service.get_declaracion(session, principal, ddjj_id)
    if not await ddjj_service.puede_operar(session, principal, ddjj.registro_id):
        raise ProblemError(
            HTTPStatus.FORBIDDEN,
            "No tenés un cargo vigente en este registro para operar su declaración jurada.",
        )
    if ddjj.estado != EstadoDDJJ.BORRADOR.value:
        raise ProblemError(
            HTTPStatus.CONFLICT,
            "La declaración jurada ya fue presentada: se corrige con una rectificativa.",
        )
    return ddjj


async def _contexto(session: AsyncSession, ddjj: DeclaracionJurada) -> minutas.ContextoMinuta:
    desde, hasta = ddjj_service.rango_periodo(ddjj.periodo)
    cargos = await ddjj_service.cargos_en_periodo(session, ddjj.registro_id, ddjj.periodo)
    candidatos: dict[uuid.UUID, minutas.Candidato] = {}
    for cargo in cargos:
        escribano = await session.get(Escribano, cargo.escribano_id)
        if escribano is None or escribano.id in candidatos:
            continue
        candidatos[escribano.id] = minutas.Candidato(
            escribano_id=escribano.id,
            apellido=escribano.persona.apellido,
            nombre=escribano.persona.nombre,
            matricula=escribano.matricula_numero,
            cargo=cargo.cargo,
        )
    declarados = frozenset(
        (a.tipo_protocolo, a.numero_escritura)
        for a in await ddjj_service.list_actos(session, ddjj.id)
    )
    registro = await session.get(RegistroNotarial, ddjj.registro_id)
    assert registro is not None  # noqa: S101 - FK
    return minutas.ContextoMinuta(
        periodo_desde=desde,
        periodo_hasta=hasta,
        hoy=today_local(),
        registro_numero=registro.numero_registro,
        candidatos=tuple(candidatos.values()),
        declarados=declarados,
    )


async def analizar_minuta(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    ddjj_id: uuid.UUID,
    *,
    archivo: UploadFile | None,
    texto: str | None,
) -> Sugerencia:
    if (archivo is None) == (texto is None or not texto.strip()):
        raise _invalid("Subí el archivo de la minuta o pegá su texto (uno de los dos).")
    ddjj = await _ddjj_operable(session, principal, ddjj_id)
    inicio = time.perf_counter_ns()
    if archivo is not None:
        try:
            validado = await storage.validar(archivo, get_settings().max_upload_bytes)
            leido = await lectura.leer_minuta(validado)
        except ArchivoInvalidoError as exc:
            raise _archivo_error(exc) from exc
        except lectura.OcrNoDisponibleError as exc:
            raise _ocr_no_disponible() from exc
        contenido, entrada = leido.contenido, leido.metadatos
    else:
        assert texto is not None  # noqa: S101 - garantizado por la validación de arriba
        if len(texto) > MAX_TEXTO:
            raise _invalid(f"El texto supera los {MAX_TEXTO:,} caracteres.".replace(",", "."))
        contenido, entrada = texto, lectura.metadatos_texto(texto)
    resultado = minutas.extraer(contenido, await _contexto(session, ddjj))
    sugerencia = _registrar(
        session,
        ctx,
        principal,
        tipo=TipoSugerencia.EXTRACCION_MINUTA,
        motor=MOTOR_MINUTA,
        version=MOTOR_MINUTA_VERSION,
        resultado=resultado,
        entrada=entrada,
        tiempo_ms=_ms(inicio),
        ddjj_id=ddjj.id,
    )
    await session.commit()
    return sugerencia


# --------------------------------------------------------------------------- DNI


async def analizar_dni(
    session: AsyncSession, ctx: RequestContext, principal: Principal, archivo: UploadFile
) -> Sugerencia:
    inicio = time.perf_counter_ns()
    try:
        validado = await storage.validar(archivo, get_settings().max_upload_bytes)
        leido = await lectura.leer_dni(validado)
    except ArchivoInvalidoError as exc:
        raise _archivo_error(exc) from exc
    datos = next((d for d in map(dni.parsear_pdf417, leido.codigos) if d is not None), None)
    if datos is None:
        datos = dni.parsear_mrz(leido.lineas_mrz, today_local())
    if datos is None:
        disponible, _ = lectura.estado_ocr()
        raise _invalid(
            "No se pudo leer el DNI. Subí una foto nítida y sin reflejos del frente (con el "
            "código de barras)"
            + (" o del dorso (con las tres líneas de caracteres)." if disponible else ".")
        )
    ya_en_padron = await session.scalar(
        select(Persona.id).where(Persona.numero_documento == datos.numero).limit(1)
    )
    resultado = dni.a_resultado(datos, ya_en_padron is not None)
    sugerencia = _registrar(
        session,
        ctx,
        principal,
        tipo=TipoSugerencia.OCR_DNI,
        motor=datos.motor,
        version=MOTOR_DNI_VERSION,
        resultado=resultado,
        entrada=leido.metadatos,
        tiempo_ms=_ms(inicio),
    )
    await session.commit()
    return sugerencia


# --------------------------------------------------------------------------- consulta


async def get_sugerencia(
    session: AsyncSession, principal: Principal, sugerencia_id: uuid.UUID, *, lock: bool = False
) -> Sugerencia:
    """Cada sugerencia la ve solo quien la pidió (trae datos del documento que analizó)."""
    stmt = select(Sugerencia).where(
        Sugerencia.id == sugerencia_id, Sugerencia.solicitado_por_user_id == principal.user.id
    )
    if lock:
        stmt = stmt.with_for_update()
    sugerencia = await session.scalar(stmt)
    if sugerencia is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "La sugerencia no existe.")
    return sugerencia


def _pendiente(sugerencia: Sugerencia, tipo: TipoSugerencia) -> None:
    if sugerencia.tipo != tipo.value:
        raise _invalid("La sugerencia no es de este tipo.")
    if sugerencia.estado != EstadoSugerencia.SUGERIDO_POR_IA.value:
        raise ProblemError(HTTPStatus.CONFLICT, "La sugerencia ya fue ratificada o descartada.")


def _texto(valor: object) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return f"{valor:.2f}"
    if isinstance(valor, date | uuid.UUID):
        return str(valor)
    if hasattr(valor, "value"):
        return str(valor.value)
    return str(valor)


def campos_modificados(sugerencia: Sugerencia, confirmados: dict[str, object]) -> list[str]:
    """Campos en que la persona se apartó de lo sugerido (incluye los que el motor no propuso)."""
    campos: dict[str, Any] = sugerencia.salida["campos"]
    return sorted(
        nombre
        for nombre, campo in campos.items()
        if nombre in confirmados and _texto(confirmados[nombre]) != campo["valor"]
    )


def _resolver(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    sugerencia: Sugerencia,
    confirmados: dict[str, object],
    datos_json: dict[str, Any],
) -> list[str]:
    modificados = campos_modificados(sugerencia, confirmados)
    sugerencia.estado = EstadoSugerencia.RATIFICADA.value
    sugerencia.resuelto_por_user_id = principal.user.id
    sugerencia.resuelto_en = datetime.now(UTC)
    sugerencia.datos_confirmados = datos_json
    sugerencia.campos_modificados = modificados
    record_audit(
        session,
        ctx,
        AuditEvent.IA_SUGERENCIA_RATIFICADA,
        actor_user_id=principal.user.id,
        details={
            "sugerencia_id": str(sugerencia.id),
            "tipo": sugerencia.tipo,
            "motor": f"{sugerencia.motor} {sugerencia.motor_version}",
            "confianza": str(sugerencia.confianza),
            "fue_modificada": bool(modificados),
            "campos_modificados": modificados,
            **({"acto_id": str(sugerencia.acto_id)} if sugerencia.acto_id else {}),
            **({"escribano_id": str(sugerencia.escribano_id)} if sugerencia.escribano_id else {}),
        },
    )
    return modificados


async def ratificar_acto(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    sugerencia_id: uuid.UUID,
    data: ActoIn,
) -> tuple[Sugerencia, Acto]:
    sugerencia = await get_sugerencia(session, principal, sugerencia_id, lock=True)
    _pendiente(sugerencia, TipoSugerencia.EXTRACCION_MINUTA)
    assert sugerencia.ddjj_id is not None  # noqa: S101 - CHECK minuta_ddjj
    acto_id = uuid.uuid4()
    sugerencia.acto_id = acto_id
    _resolver(session, ctx, principal, sugerencia, dict(data), data.model_dump(mode="json"))
    # Mismas validaciones, permisos y auditoría que la carga manual; confirma todo junto.
    acto = await ddjj_service.agregar_acto(
        session, ctx, principal, sugerencia.ddjj_id, data, acto_id=acto_id
    )
    await session.refresh(sugerencia)
    return sugerencia, acto


async def ratificar_escribano(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    sugerencia_id: uuid.UUID,
    data: EscribanoIn,
) -> tuple[Sugerencia, Escribano]:
    sugerencia = await get_sugerencia(session, principal, sugerencia_id, lock=True)
    _pendiente(sugerencia, TipoSugerencia.OCR_DNI)
    escribano_id = uuid.uuid4()
    sugerencia.escribano_id = escribano_id
    _resolver(session, ctx, principal, sugerencia, dict(data.persona), data.model_dump(mode="json"))
    escribano = await padron_service.create_escribano(
        session, ctx, principal.user, data, escribano_id=escribano_id
    )
    await session.refresh(sugerencia)
    return sugerencia, escribano


async def descartar(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    sugerencia_id: uuid.UUID,
    motivo: str | None,
) -> Sugerencia:
    sugerencia = await get_sugerencia(session, principal, sugerencia_id, lock=True)
    if sugerencia.estado != EstadoSugerencia.SUGERIDO_POR_IA.value:
        raise ProblemError(HTTPStatus.CONFLICT, "La sugerencia ya fue ratificada o descartada.")
    sugerencia.estado = EstadoSugerencia.DESCARTADA.value
    sugerencia.resuelto_por_user_id = principal.user.id
    sugerencia.resuelto_en = datetime.now(UTC)
    sugerencia.motivo_descarte = motivo
    record_audit(
        session,
        ctx,
        AuditEvent.IA_SUGERENCIA_DESCARTADA,
        actor_user_id=principal.user.id,
        details={"sugerencia_id": str(sugerencia.id), "tipo": sugerencia.tipo},
    )
    await session.commit()
    await session.refresh(sugerencia)
    return sugerencia
