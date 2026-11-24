"""Registro de prueba y vínculo de cuentas existentes con el padrón.

El registro de prueba es un registro notarial ficticio, con un escribano ficticio como titular,
para que una cuenta de autogestión practique la carga de DDJJ en el servidor de prueba. Solo
existe en development y staging. Se identifica por el nombre (`NOMBRE_REGISTRO`): la baja
rechaza cualquier registro que no lo tenga, así nunca toca uno real.

Nada se borra (regla INM): la baja cierra el cargo, cierra el registro, pasa al escribano
ficticio a CESANTE y desvincula la cuenta. Las DDJJ y boletas de prueba quedan en el registro
cerrado. Todo queda en `audit_security_logs`.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.core.config import Environment
from app.modules.iam.catalog import Perm
from app.modules.iam.models import User
from app.modules.padron import a_cargo
from app.modules.padron.catalog import Cargo, EstadoMatricula, EstadoRegistro
from app.modules.padron.models import (
    Adscripcion,
    Circunscripcion,
    DomicilioRegistro,
    Escribano,
    HistorialEstado,
    Persona,
    RegistroNotarial,
)
from app.modules.padron.service import (
    CARGO_FIELDS,
    CIRC_FIELDS,
    ESC_FIELDS,
    PER_FIELDS,
    REG_FIELDS,
    _snapshot,
)

NUMERO_REGISTRO_PRUEBA = 9999
NOMBRE_REGISTRO = "REGISTRO DE PRUEBA (no oficial)"
NOMBRE_CIRCUNSCRIPCION = "Circunscripción de prueba (no oficial)"
APELLIDO_PRUEBA = "PRUEBA (no oficial)"
MOTIVO_BAJA = "Baja del registro de prueba (no oficial)."
ENTORNOS_PERMITIDOS = frozenset({Environment.DEVELOPMENT, Environment.STAGING, Environment.TEST})


class PruebaError(Exception):
    """La operación no procede; el mensaje se muestra tal cual en la consola."""


@dataclass(frozen=True)
class RegistroPrueba:
    registro_id: uuid.UUID
    numero_registro: int
    escribano_id: uuid.UUID
    user_id: uuid.UUID | None


def _exigir_entorno(entorno: Environment) -> None:
    if entorno not in ENTORNOS_PERMITIDOS:
        raise PruebaError(
            "El registro de prueba solo se usa en desarrollo o en el servidor de prueba "
            f"(ENVIRONMENT={entorno.value})."
        )


def _exigir_operador(actor: User, *permisos: Perm) -> None:
    """Quien figura en la auditoría tiene que poder hacer lo mismo desde la pantalla: si no,
    el registro diría que lo hizo alguien sin facultad para hacerlo."""
    if not actor.is_active:
        raise PruebaError(f"La cuenta del operador {actor.email} está suspendida.")
    faltan = [p.value for p in permisos if p.value not in actor.permission_codes]
    if faltan:
        raise PruebaError(
            f"El operador {actor.email} no tiene permiso para esto ({', '.join(faltan)})."
        )


async def cuenta_por_email(session: AsyncSession, email: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise PruebaError(f"No existe una cuenta con el correo {email}.")
    return user


def _exigir_cuenta_de_escribano(cuenta: User) -> None:
    if not cuenta.is_active:
        raise PruebaError(f"La cuenta {cuenta.email} está suspendida.")
    if "ROLE_ESCRIBANO" not in cuenta.role_codes:
        raise PruebaError(f"La cuenta {cuenta.email} no tiene el rol de escribano.")


async def _escribano_de(session: AsyncSession, cuenta: User) -> Escribano | None:
    return await session.scalar(select(Escribano).where(Escribano.user_id == cuenta.id))


async def _vincular(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    escribano: Escribano,
    cuenta: User,
    *,
    prueba: bool,
) -> None:
    escribano.user_id = cuenta.id
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_CUENTA_VINCULADA,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        target_user_id=cuenta.id,
        old_value={"user_id": None},
        new_value={"user_id": str(cuenta.id)},
        details={
            "escribano_id": str(escribano.id),
            "email": cuenta.email,
            "origen": "cli",
            "registro_de_prueba": prueba,
        },
    )


async def vincular_cuenta(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    cuenta: User,
    cuit_escribano: str,
) -> Escribano:
    """Vincula una cuenta existente con el escribano del padrón que tiene ese CUIT.

    El CUIT de la cuenta tiene que ser el del escribano: evita darle a alguien la autogestión
    de otra persona por un error de tipeo."""
    _exigir_operador(actor, Perm.ESCRIBANOS_WRITE)
    _exigir_cuenta_de_escribano(cuenta)
    if cuenta.cuit != cuit_escribano:
        raise PruebaError(
            f"El CUIT de la cuenta ({cuenta.cuit}) no es el del escribano ({cuit_escribano})."
        )
    if (actual := await _escribano_de(session, cuenta)) is not None:
        raise PruebaError(f"La cuenta ya está vinculada al escribano {actual.id}.")
    escribano = await session.scalar(
        select(Escribano)
        .join(Persona, Persona.id == Escribano.persona_id)
        .where(Persona.cuit == cuit_escribano)
        .with_for_update(of=Escribano)
    )
    if escribano is None:
        raise PruebaError(f"No hay un escribano con CUIT {cuit_escribano} en el padrón.")
    if escribano.user_id is not None:
        raise PruebaError("Ese escribano ya tiene otra cuenta de autogestión.")
    await _vincular(session, ctx, actor, escribano, cuenta, prueba=False)
    await session.commit()
    return escribano


async def crear_registro_prueba(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    cuenta: User,
    *,
    entorno: Environment,
    desde: date,
    numero_registro: int = NUMERO_REGISTRO_PRUEBA,
) -> RegistroPrueba:
    """Crea el registro de prueba con un escribano ficticio titular desde `desde` y le vincula
    la cuenta. Todo en una transacción: o queda completo o no queda nada."""
    _exigir_entorno(entorno)
    _exigir_operador(actor, Perm.ESCRIBANOS_WRITE)
    _exigir_cuenta_de_escribano(cuenta)
    if (actual := await _escribano_de(session, cuenta)) is not None:
        raise PruebaError(
            f"La cuenta {cuenta.email} ya está vinculada a un escribano ({actual.id}): "
            "dale de baja el registro de prueba antes de crear otro."
        )
    if await session.scalar(
        select(RegistroNotarial.id).where(RegistroNotarial.numero_registro == numero_registro)
    ):
        raise PruebaError(f"Ya existe un registro con el número {numero_registro}.")
    if await session.scalar(select(Persona.id).where(Persona.cuit == cuenta.cuit)):
        raise PruebaError(
            f"Ya hay una persona del padrón con el CUIT de la cuenta ({cuenta.cuit}): "
            "vinculala con `vincular-cuenta` en lugar de crear un registro de prueba."
        )

    circ = await session.scalar(
        select(Circunscripcion).where(Circunscripcion.nombre == NOMBRE_CIRCUNSCRIPCION)
    )
    if circ is None:
        circ = Circunscripcion(
            id=uuid.uuid4(),
            nombre=NOMBRE_CIRCUNSCRIPCION,
            descripcion="Datos ficticios para practicar en el servidor de prueba.",
            is_active=True,
            created_by_user_id=actor.id,
        )
        session.add(circ)
        record_audit(
            session,
            ctx,
            AuditEvent.PADRON_CIRCUNSCRIPCION_CREATED,
            actor_user_id=actor.id,
            new_value=_snapshot(circ, CIRC_FIELDS),
            details={"circunscripcion_id": str(circ.id), "origen": "cli", "prueba": True},
        )

    registro = RegistroNotarial(
        id=uuid.uuid4(),
        numero_registro=numero_registro,
        nombre_fantasia=NOMBRE_REGISTRO,
        circunscripcion_id=circ.id,
        departamento="Capital",
        domicilio_legal="Domicilio ficticio (registro de prueba)",
        email=cuenta.email,
        fecha_creacion=desde,
        estado=EstadoRegistro.ACTIVO.value,
        created_by_user_id=actor.id,
    )
    session.add(registro)
    session.add(
        DomicilioRegistro(
            registro_id=registro.id,
            domicilio=registro.domicilio_legal,
            fecha_desde=desde,
            created_by_user_id=actor.id,
        )
    )
    persona = Persona(
        id=uuid.uuid4(),
        cuit=cuenta.cuit,
        tipo_documento="DNI",
        numero_documento=cuenta.cuit[2:10],
        apellido=APELLIDO_PRUEBA,
        nombre=cuenta.full_name[:100],
        email=cuenta.email,
        created_by_user_id=actor.id,
    )
    session.add(persona)
    escribano = Escribano(
        id=uuid.uuid4(),
        persona_id=persona.id,
        matricula_numero=numero_registro,
        fecha_matriculacion=desde,
        estado_matricula=EstadoMatricula.ACTIVO.value,
        created_by_user_id=actor.id,
    )
    session.add(escribano)
    cargo = Adscripcion(
        id=uuid.uuid4(),
        escribano_id=escribano.id,
        registro_id=registro.id,
        cargo=Cargo.TITULAR.value,
        fecha_desde=desde,
        is_current=True,
        created_by_user_id=actor.id,
    )
    session.add(cargo)
    detalle = {"origen": "cli", "prueba": True}
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_REGISTRO_CREATED,
        actor_user_id=actor.id,
        new_value=_snapshot(registro, REG_FIELDS),
        details={"registro_id": str(registro.id), **detalle},
    )
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_ESCRIBANO_CREATED,
        actor_user_id=actor.id,
        new_value={**_snapshot(persona, PER_FIELDS), **_snapshot(escribano, ESC_FIELDS)},
        details={"escribano_id": str(escribano.id), **detalle},
    )
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_CARGO_ASSIGNED,
        actor_user_id=actor.id,
        new_value=_snapshot(cargo, CARGO_FIELDS),
        details={
            "escribano_id": str(escribano.id),
            "numero_registro": numero_registro,
            **detalle,
        },
    )
    await session.flush()
    await _vincular(session, ctx, actor, escribano, cuenta, prueba=True)
    await session.commit()
    return RegistroPrueba(registro.id, numero_registro, escribano.id, cuenta.id)


async def baja_registro_prueba(
    session: AsyncSession,
    ctx: RequestContext,
    actor: User,
    *,
    entorno: Environment,
    hoy: date,
    numero_registro: int = NUMERO_REGISTRO_PRUEBA,
) -> RegistroPrueba:
    """Baja lógica del registro de prueba: cierra cargos y registro, pasa al escribano ficticio
    a CESANTE y desvincula la cuenta (que sigue activa). Las DDJJ y boletas quedan."""
    _exigir_entorno(entorno)
    _exigir_operador(actor, Perm.ESCRIBANOS_WRITE, Perm.ESCRIBANOS_STATUS)
    registro = await session.scalar(
        select(RegistroNotarial)
        .where(RegistroNotarial.numero_registro == numero_registro)
        .with_for_update(of=RegistroNotarial)
    )
    if registro is None:
        raise PruebaError(f"No existe el registro {numero_registro}.")
    if registro.nombre_fantasia != NOMBRE_REGISTRO:
        raise PruebaError(
            f"El registro {numero_registro} no es un registro de prueba: no se da de baja."
        )
    # Dado de baja: sin titular (vacante) y con sus cargos cerrados.
    if registro.estado == EstadoRegistro.VACANTE:
        raise PruebaError(f"El registro de prueba {numero_registro} ya está dado de baja.")

    cargos = list(
        (
            await session.scalars(
                select(Adscripcion).where(
                    Adscripcion.registro_id == registro.id, Adscripcion.is_current.is_(True)
                )
            )
        ).all()
    )
    titular = next((c.escribano for c in cargos if c.cargo == Cargo.TITULAR), None)
    if titular is None:
        raise PruebaError(f"El registro de prueba {numero_registro} no tiene titular vigente.")
    for cargo in cargos:
        old = _snapshot(cargo, CARGO_FIELDS)
        cargo.fecha_hasta = max(hoy, cargo.inicio)
        cargo.is_current = False
        cargo.motivo_cierre = MOTIVO_BAJA
        if cargo.cargo == Cargo.TITULAR:
            await a_cargo.cerrar_por_cierre_de_titular(session, ctx, actor, cargo)
        record_audit(
            session,
            ctx,
            AuditEvent.PADRON_CARGO_CLOSED,
            actor_user_id=actor.id,
            old_value=old,
            new_value=_snapshot(cargo, CARGO_FIELDS),
            details={
                "cargo_id": str(cargo.id),
                "escribano_id": str(cargo.escribano_id),
                "numero_registro": numero_registro,
                "motivo": MOTIVO_BAJA,
                "origen": "cli",
                "prueba": True,
            },
        )

    old_estado = registro.estado
    registro.estado = EstadoRegistro.VACANTE.value
    record_audit(
        session,
        ctx,
        AuditEvent.PADRON_REGISTRO_CLOSED,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value={"estado": old_estado},
        new_value={"estado": registro.estado},
        details={
            "registro_id": str(registro.id),
            "motivo": MOTIVO_BAJA,
            "origen": "cli",
            "prueba": True,
        },
    )

    user_id = titular.user_id
    if titular.estado_matricula == EstadoMatricula.ACTIVO:
        titular.estado_matricula = EstadoMatricula.CESANTE.value
        titular.motivo_ultimo_cambio_estado = MOTIVO_BAJA
        session.add(
            HistorialEstado(
                escribano_id=titular.id,
                estado_anterior=EstadoMatricula.ACTIVO.value,
                estado_nuevo=EstadoMatricula.CESANTE.value,
                motivo=MOTIVO_BAJA,
                fecha_efectiva=hoy,
                operador_user_id=actor.id,
            )
        )
        record_audit(
            session,
            ctx,
            AuditEvent.PADRON_ESTADO_CHANGED,
            actor_user_id=actor.id,
            old_value={"estado_matricula": EstadoMatricula.ACTIVO.value},
            new_value={"estado_matricula": EstadoMatricula.CESANTE.value},
            details={"escribano_id": str(titular.id), "motivo": MOTIVO_BAJA, "prueba": True},
        )
    if user_id is not None:
        titular.user_id = None
        record_audit(
            session,
            ctx,
            AuditEvent.PADRON_CUENTA_DESVINCULADA,
            severity=Severity.WARNING,
            actor_user_id=actor.id,
            target_user_id=user_id,
            old_value={"user_id": str(user_id)},
            new_value={"user_id": None},
            details={"escribano_id": str(titular.id), "origen": "cli", "prueba": True},
        )
    await session.commit()
    return RegistroPrueba(registro.id, numero_registro, titular.id, user_id)
