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
from dataclasses import dataclass
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
from app.modules.ia import dni, indice, lectura, minutas, vision
from app.modules.ia.catalog import (
    MOTOR_DNI_VERSION,
    MOTOR_INDICE_OCR,
    MOTOR_INDICE_VERSION,
    MOTOR_INDICE_VISION,
    MOTOR_MINUTA,
    MOTOR_MINUTA_VERSION,
    EstadoSugerencia,
    TipoSugerencia,
)
from app.modules.ia.models import Sugerencia
from app.modules.ia.resultado import Resultado, huella
from app.modules.iam.deps import Principal
from app.modules.padron import service as padron_service
from app.modules.padron.models import Escribano, Persona, RegistroNotarial
from app.modules.padron.schemas import EscribanoIn
from app.modules.pagos import storage
from app.modules.pagos.storage import ArchivoInvalidoError, ArchivoValidado

MAX_TEXTO = minutas.MAX_CARACTERES


def _invalid(message: str, status: HTTPStatus = HTTPStatus.UNPROCESSABLE_ENTITY) -> ProblemError:
    return ProblemError(status, message)


def _archivo_error(exc: ArchivoInvalidoError) -> ProblemError:
    return ProblemError(HTTPStatus(exc.status), str(exc))


def _cola_llena() -> ProblemError:
    return ProblemError(
        HTTPStatus.SERVICE_UNAVAILABLE,
        "Hay muchas lecturas en curso: probá de nuevo en un minuto.",
    )


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
        salida=resultado.a_registro(),
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
    # Toda escritura del año del registro (no solo de esta DDJJ): la numeración es anual.
    del_anio = await ddjj_service.actos_del_anio(session, ddjj.registro_id, int(ddjj.periodo[:4]))
    declarados = frozenset((a.tipo_protocolo, a.numero) for a in del_anio)
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
) -> tuple[Sugerencia, Resultado]:
    if (archivo is None) == (texto is None or not texto.strip()):
        raise _invalid("Subí el archivo de la minuta o pegá su texto (uno de los dos).")
    if texto is not None and len(texto) > MAX_TEXTO:
        raise _invalid(f"El texto supera los {MAX_TEXTO:,} caracteres.".replace(",", "."))
    await _ddjj_operable(session, principal, ddjj_id)
    # La lectura puede tardar (OCR): no se retiene una conexión de la base mientras tanto.
    await session.commit()
    inicio = time.perf_counter_ns()
    try:
        if archivo is not None:
            validado = await storage.validar(archivo, get_settings().max_upload_bytes)
            leido = await lectura.leer_minuta(validado)
            contenido, entrada = leido.contenido, leido.metadatos
        else:
            assert texto is not None  # noqa: S101 - garantizado por la validación de arriba
            contenido, entrada = texto, lectura.metadatos_texto(texto)
    except ArchivoInvalidoError as exc:
        raise _archivo_error(exc) from exc
    except lectura.OcrNoDisponibleError as exc:
        raise _ocr_no_disponible() from exc
    except lectura.ColaLlenaError as exc:
        raise _cola_llena() from exc
    if len(contenido) > MAX_TEXTO:
        raise _invalid("El documento tiene demasiado texto: subí solo la minuta.")
    # Se revalida: la DDJJ pudo presentarse (o el cargo cerrarse) durante la lectura.
    ddjj = await _ddjj_operable(session, principal, ddjj_id)
    contexto = await _contexto(session, ddjj)
    try:
        resultado = await lectura.en_hilo(minutas.extraer, contenido, contexto)
    except lectura.ColaLlenaError as exc:
        raise _cola_llena() from exc
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
    return sugerencia, resultado


# --------------------------------------------------------------------------- índice del protocolo

# Confianza del lector (la visión no informa una por dato). Las reglas derivadas llevan la suya.
CONFIANZA_VISION = Decimal("0.85")
CONFIANZA_OCR = Decimal("0.55")


@dataclass(frozen=True)
class LecturaIndice:
    lote: uuid.UUID
    motor: str
    sugerencias: list[tuple[Sugerencia, Resultado]]


async def _leer_foto(
    validado: ArchivoValidado, numero: int
) -> tuple[list[indice.Renglon], str, dict[str, Any], str | None]:
    """Renglones de una foto, el motor que los leyó, metadatos y, si hubo, el motivo del
    respaldo local."""
    respaldo = None
    if vision.configurada():
        try:
            jpeg = await lectura.foto_para_vision(validado)
            leido = await vision.transcribir(jpeg)
            renglones = indice.renglones_de_vision(leido.texto, numero)
            return (
                renglones,
                MOTOR_INDICE_VISION,
                {"modelo": leido.modelo, "tokens": leido.tokens},
                None,
            )
        except (vision.VisionNoDisponibleError, indice.RespuestaInvalidaError) as exc:
            respaldo = str(exc)
    texto = await lectura.ocr_indice(validado)
    _, idiomas = lectura.estado_ocr()
    return indice.renglones_de_ocr(texto, numero), MOTOR_INDICE_OCR, {"ocr": idiomas}, respaldo


async def analizar_indice(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    ddjj_id: uuid.UUID,
    archivos: list[UploadFile],
) -> LecturaIndice:
    """Fotos del índice del protocolo → una sugerencia de acto por renglón. Nada se carga en la
    DDJJ hasta que la persona ratifica cada renglón (HIC)."""
    settings = get_settings()
    if not archivos:
        raise _invalid("Subí al menos una foto del índice.")
    if len(archivos) > settings.IA_INDICE_MAX_FOTOS:
        raise _invalid(f"Subí hasta {settings.IA_INDICE_MAX_FOTOS} fotos por vez.")
    await _ddjj_operable(session, principal, ddjj_id)
    # La lectura puede tardar (visión u OCR): no se retiene una conexión mientras tanto.
    await session.commit()
    inicio = time.perf_counter_ns()
    leidos: list[tuple[indice.Renglon, dict[str, Any]]] = []
    motores: set[str] = set()
    respaldos: list[str] = []
    try:
        for numero, archivo in enumerate(archivos, start=1):
            validado = await storage.validar(archivo, settings.max_upload_bytes)
            renglones, motor, extra, respaldo = await _leer_foto(validado, numero)
            motores.add(motor)
            if respaldo:
                respaldos.append(respaldo)
            meta = {
                "origen": "indice",
                "mime_type": validado.mime_type,
                "bytes": validado.tamano,
                "sha256": validado.sha256,
                "foto": numero,
                "fotos": len(archivos),
                "motor": motor,
                **extra,
            }
            leidos += [(r, meta) for r in renglones]
    except ArchivoInvalidoError as exc:
        raise _archivo_error(exc) from exc
    except lectura.OcrNoDisponibleError as exc:
        raise ProblemError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "La lectura de fotos no está disponible en este momento: cargá los actos a mano.",
        ) from exc
    except lectura.ColaLlenaError as exc:
        raise _cola_llena() from exc
    if not leidos:
        raise _invalid(
            "No se encontraron renglones de escrituras en la foto. Probá con una foto más "
            "nítida, de frente y con buena luz, que muestre el número y la fecha de cada "
            "escritura."
        )
    # Se revalida: la DDJJ pudo presentarse (o el cargo cerrarse) durante la lectura.
    ddjj = await _ddjj_operable(session, principal, ddjj_id)
    contexto = await _contexto(session, ddjj)
    tiempo = _ms(inicio)
    lote = uuid.uuid4()
    sugerencias = []
    for renglon_numero, (renglon, meta) in enumerate(leidos, start=1):
        motor = meta["motor"]
        confianza = CONFIANZA_VISION if motor == MOTOR_INDICE_VISION else CONFIANZA_OCR
        resultado = indice.a_resultado(renglon, contexto, confianza=confianza)
        entrada = {**meta, "lote": str(lote), "renglon": renglon_numero}
        sugerencia = _registrar(
            session,
            ctx,
            principal,
            tipo=TipoSugerencia.EXTRACCION_INDICE,
            motor=motor,
            version=MOTOR_INDICE_VERSION,
            resultado=resultado,
            entrada=entrada,
            tiempo_ms=tiempo,
            ddjj_id=ddjj.id,
        )
        sugerencias.append((sugerencia, resultado))
    # Registro del procesamiento: qué proveedor leyó las fotos (externo o local) y si hubo
    # respaldo. Sin datos de las fotos.
    record_audit(
        session,
        ctx,
        AuditEvent.IA_INDICE_LEIDO,
        actor_user_id=principal.user.id,
        details={
            "ddjj_id": str(ddjj.id),
            "lote": str(lote),
            "fotos": len(archivos),
            "renglones": len(sugerencias),
            "motores": sorted(motores),
            "procesamiento_externo": ("deepseek" if MOTOR_INDICE_VISION in motores else None),
            "respaldo_local": respaldos or None,
        },
    )
    await session.commit()
    motor_lote = MOTOR_INDICE_VISION if MOTOR_INDICE_VISION in motores else MOTOR_INDICE_OCR
    return LecturaIndice(lote, motor_lote, sugerencias)


# --------------------------------------------------------------------------- DNI


async def analizar_dni(
    session: AsyncSession, ctx: RequestContext, principal: Principal, archivo: UploadFile
) -> tuple[Sugerencia, Resultado]:
    # Permisos ya verificados: se libera la conexión antes de leer la imagen.
    await session.commit()
    inicio = time.perf_counter_ns()
    try:
        validado = await storage.validar(archivo, get_settings().max_upload_bytes)
        leido = await lectura.leer_dni(validado)
    except ArchivoInvalidoError as exc:
        raise _archivo_error(exc) from exc
    except lectura.ColaLlenaError as exc:
        raise _cola_llena() from exc
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
    resultado = dni.a_resultado(datos, ya_en_padron is not None, today_local())
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
    return sugerencia, resultado


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


def _pendiente(sugerencia: Sugerencia, tipos: TipoSugerencia | tuple[TipoSugerencia, ...]) -> None:
    aceptados = (tipos,) if isinstance(tipos, TipoSugerencia) else tipos
    if sugerencia.tipo not in {t.value for t in aceptados}:
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


def huellas_confirmadas(sugerencia: Sugerencia, confirmados: dict[str, object]) -> dict[str, Any]:
    """Huella de lo que confirmó la persona en cada campo que el motor evaluó."""
    campos: dict[str, Any] = sugerencia.salida["campos"]
    return {k: huella(_texto(confirmados[k])) for k in campos if k in confirmados}


def campos_modificados(sugerencia: Sugerencia, confirmadas: dict[str, Any]) -> list[str]:
    """Campos en que la persona se apartó de lo sugerido (incluye los que el motor no propuso).

    Se comparan huellas: el registro no guarda los valores."""
    campos: dict[str, Any] = sugerencia.salida["campos"]
    return sorted(k for k, h in confirmadas.items() if h != campos[k]["huella"])


def _resolver(
    session: AsyncSession,
    ctx: RequestContext,
    principal: Principal,
    sugerencia: Sugerencia,
    confirmados: dict[str, object],
) -> list[str]:
    confirmadas = huellas_confirmadas(sugerencia, confirmados)
    modificados = campos_modificados(sugerencia, confirmadas)
    sugerencia.estado = EstadoSugerencia.RATIFICADA.value
    sugerencia.resuelto_por_user_id = principal.user.id
    sugerencia.resuelto_en = datetime.now(UTC)
    sugerencia.datos_confirmados = confirmadas
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
    _pendiente(sugerencia, (TipoSugerencia.EXTRACCION_MINUTA, TipoSugerencia.EXTRACCION_INDICE))
    assert sugerencia.ddjj_id is not None  # noqa: S101 - CHECK minuta_ddjj
    acto_id = uuid.uuid4()
    sugerencia.acto_id = acto_id
    _resolver(session, ctx, principal, sugerencia, dict(data))
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
    _resolver(session, ctx, principal, sugerencia, dict(data.persona))
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
