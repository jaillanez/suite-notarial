"""Endpoints del padrón notarial: /api/v1/padron."""

import uuid
from datetime import date
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select

from app.common.cuit import format_cuit
from app.common.dates import today_local
from app.common.deps import SessionDep, SettingsDep
from app.common.pagination import Page, PageParamsDep
from app.core.errors import ProblemError
from app.core.mail import send_safely
from app.modules.iam import users_service
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal, RequestContextDep, require_permissions
from app.modules.iam.mails import account_created_mail
from app.modules.iam.models import User
from app.modules.iam.router_auth import MailerDep
from app.modules.iam.schemas import UserCreate
from app.modules.padron import licencias, service
from app.modules.padron.catalog import (
    DEPARTAMENTOS_SAN_JUAN,
    REQUIERE_RESOLUCION,
    TRANSICIONES,
    Cargo,
    EstadoDesignacion,
    EstadoMatricula,
    EstadoRegistro,
)
from app.modules.padron.models import (
    Adscripcion,
    Circunscripcion,
    DesignacionACargo,
    Escribano,
    Licencia,
    RegistroNotarial,
)
from app.modules.padron.schemas import (
    AntiguedadOut,
    CargoAsignacion,
    CargoCierre,
    CargoOut,
    CargoResumen,
    CircunscripcionIn,
    CircunscripcionOut,
    CircunscripcionUpdate,
    CuentaIn,
    DatosACompletar,
    DesignacionResumen,
    DomicilioCambio,
    DomicilioOut,
    EscribanoDetalle,
    EscribanoIn,
    EscribanoOut,
    EscribanoUpdate,
    EstadoCambio,
    HistorialOut,
    LicenciaAnulacion,
    LicenciaFin,
    LicenciaIn,
    LicenciaOut,
    PersonaOut,
    PrimeraEscrituraIn,
    PrimeraEscrituraOut,
    RegistroCierre,
    RegistroDetalle,
    RegistroIn,
    RegistroOut,
    RegistroUpdate,
)

router = APIRouter(prefix="/padron", tags=["padron"])

CanRead = Annotated[Principal, Depends(require_permissions(Perm.ESCRIBANOS_READ))]
CanWrite = Annotated[Principal, Depends(require_permissions(Perm.ESCRIBANOS_WRITE))]
CanChangeStatus = Annotated[Principal, Depends(require_permissions(Perm.ESCRIBANOS_STATUS))]
CanCreateAccount = Annotated[
    Principal, Depends(require_permissions(Perm.ESCRIBANOS_WRITE, Perm.USERS_WRITE))
]


# --------------------------------------------------------------------------- serialización


def circ_out(item: Circunscripcion) -> CircunscripcionOut:
    return CircunscripcionOut(
        id=item.id, nombre=item.nombre, descripcion=item.descripcion, is_active=item.is_active
    )


def cargo_resumen(item: Adscripcion) -> CargoResumen:
    persona = item.escribano.persona
    return CargoResumen(
        adscripcion_id=item.id,
        escribano_id=item.escribano_id,
        matricula_numero=item.escribano.matricula_numero,
        apellido_nombre=f"{persona.apellido}, {persona.nombre}",
        cargo=Cargo(item.cargo),
        fecha_desde=item.fecha_desde,
        estado_matricula=EstadoMatricula(item.escribano.estado_matricula),
    )


def registro_out(item: RegistroNotarial, cargos: list[Adscripcion]) -> RegistroOut:
    titular = next((c for c in cargos if c.cargo == Cargo.TITULAR), None)
    return RegistroOut(
        id=item.id,
        numero_registro=item.numero_registro,
        nombre_fantasia=item.nombre_fantasia,
        circunscripcion=circ_out(item.circunscripcion),
        departamento=item.departamento,
        domicilio_legal=item.domicilio_legal,
        telefono=item.telefono,
        email=item.email,
        fecha_creacion=item.fecha_creacion,
        estado=EstadoRegistro(item.estado),
        titular=cargo_resumen(titular) if titular else None,
        cantidad_adscriptos=sum(1 for c in cargos if c.cargo != Cargo.TITULAR),
    )


def escribano_out(
    item: Escribano, vigente: Adscripcion | None, en_licencia_desde: date | None = None
) -> EscribanoOut:
    persona = item.persona
    return EscribanoOut(
        id=item.id,
        matricula_numero=item.matricula_numero,
        tomo=item.tomo,
        folio=item.folio,
        fecha_matriculacion=item.fecha_matriculacion,
        estado_matricula=EstadoMatricula(item.estado_matricula),
        apellido_nombre=f"{persona.apellido}, {persona.nombre}",
        cuit=format_cuit(persona.cuit) if persona.cuit else None,
        numero_documento=persona.numero_documento,
        registro_actual=vigente.registro.numero_registro if vigente else None,
        cargo_actual=Cargo(vigente.cargo) if vigente else None,
        tiene_cuenta=item.user_id is not None,
        en_licencia_desde=en_licencia_desde,
    )


def cargo_out(item: Adscripcion) -> CargoOut:
    return CargoOut(
        id=item.id,
        registro_id=item.registro_id,
        numero_registro=item.registro.numero_registro,
        cargo=Cargo(item.cargo),
        resolucion_designacion=item.resolucion_designacion,
        fecha_desde=item.fecha_desde,
        fecha_hasta=item.fecha_hasta,
        motivo_cierre=item.motivo_cierre,
        is_current=item.is_current,
    )


def licencia_out(item: Licencia, cargada_por: str | None, hoy: date) -> LicenciaOut:
    return LicenciaOut(
        id=item.id,
        fecha_desde=item.fecha_desde,
        fecha_hasta=item.fecha_hasta,
        motivo=item.motivo,
        resolucion_respaldo=item.resolucion_respaldo,
        anulada=item.anulada,
        motivo_anulacion=item.motivo_anulacion,
        anulada_en=item.anulada_en,
        vigente=licencias.rige(item, hoy),
        cargada_por=cargada_por,
        created_at=item.created_at,
    )


async def _primera_escritura(session: SessionDep, item: Escribano) -> PrimeraEscrituraOut | None:
    if (
        item.primera_escritura_fecha is None
        or item.primera_escritura_numero is None
        or item.primera_escritura_registro is None
    ):
        return None
    email = None
    if item.primera_escritura_cargada_por_user_id is not None:
        email = await session.scalar(
            select(User.email).where(User.id == item.primera_escritura_cargada_por_user_id)
        )
    return PrimeraEscrituraOut(
        fecha=item.primera_escritura_fecha,
        numero=item.primera_escritura_numero,
        registro=item.primera_escritura_registro,
        folio=item.primera_escritura_folio,
        cargada_por=email,
        cargada_en=item.primera_escritura_cargada_en,
    )


async def _designaciones(session: SessionDep, escribano_id: uuid.UUID) -> list[DesignacionResumen]:
    result = await session.execute(
        select(DesignacionACargo)
        .where(DesignacionACargo.escribano_id == escribano_id)
        .order_by(DesignacionACargo.fecha_desde.desc(), DesignacionACargo.created_at.desc())
    )
    return [
        DesignacionResumen(
            id=d.id,
            registro_id=d.registro_id,
            numero_registro=d.registro.numero_registro,
            fecha_desde=d.fecha_desde,
            fecha_hasta=d.fecha_hasta,
            estado=EstadoDesignacion(d.estado),
            motivo=d.motivo,
        )
        for d in result.unique().scalars()
    ]


async def escribano_detalle(session: SessionDep, item: Escribano) -> EscribanoDetalle:
    cargos = await service.list_cargos(session, item.id)
    vigente = next((c for c in cargos if c.is_current), None)
    historial = await service.list_historial(session, item.id)
    hoy = today_local()
    lics = await licencias.listar(session, item.id)
    en_licencia = next((lic.fecha_desde for lic, _ in lics if licencias.rige(lic, hoy)), None)
    persona = item.persona
    base = escribano_out(item, vigente, en_licencia)
    actual = EstadoMatricula(item.estado_matricula)
    primera = await _primera_escritura(session, item)
    antiguedad = None
    if primera is not None:
        anios, meses = service.antiguedad(primera.fecha, hoy)
        antiguedad = AntiguedadOut(desde=primera.fecha, anios=anios, meses=meses)
    return EscribanoDetalle(
        **base.model_dump(),
        transiciones_permitidas=sorted(TRANSICIONES[actual]),
        transiciones_con_resolucion=sorted(
            nuevo for desde, nuevo in REQUIERE_RESOLUCION if desde == actual
        ),
        persona=PersonaOut(
            id=persona.id,
            cuit=format_cuit(persona.cuit) if persona.cuit else None,
            tipo_documento=persona.tipo_documento,
            numero_documento=persona.numero_documento,
            apellido=persona.apellido,
            nombre=persona.nombre,
            fecha_nacimiento=persona.fecha_nacimiento,
            email=persona.email,
            telefono=persona.telefono,
            domicilio_real=persona.domicilio_real,
        ),
        motivo_ultimo_cambio_estado=item.motivo_ultimo_cambio_estado,
        fecha_ultimo_cambio_estado=item.fecha_ultimo_cambio_estado,
        a_completar=service.datos_a_completar(item),
        cargos=[cargo_out(c) for c in cargos],
        historial=[
            HistorialOut(
                id=h.id,
                estado_anterior=EstadoMatricula(h.estado_anterior),
                estado_nuevo=EstadoMatricula(h.estado_nuevo),
                motivo=h.motivo,
                resolucion_respaldo=h.resolucion_respaldo,
                fecha_efectiva=h.fecha_efectiva,
                fecha_cambio=h.fecha_cambio,
                operador_email=email,
            )
            for h, email in historial
        ],
        primera_escritura=primera,
        antiguedad=antiguedad,
        licencias=[licencia_out(lic, email, hoy) for lic, email in lics],
        designaciones_a_cargo=await _designaciones(session, item.id),
    )


# --------------------------------------------------------------------------- catálogos


@router.get("/departamentos", response_model=list[str])
async def departamentos(_: CanRead) -> list[str]:
    return list(DEPARTAMENTOS_SAN_JUAN)


@router.get("/circunscripciones", response_model=list[CircunscripcionOut])
async def list_circunscripciones(_: CanRead, session: SessionDep) -> list[CircunscripcionOut]:
    return [circ_out(c) for c in await service.list_circunscripciones(session)]


@router.post("/circunscripciones", response_model=CircunscripcionOut, status_code=201)
async def create_circunscripcion(
    body: CircunscripcionIn, principal: CanWrite, session: SessionDep, ctx: RequestContextDep
) -> CircunscripcionOut:
    return circ_out(await service.create_circunscripcion(session, ctx, principal.user, body))


@router.patch("/circunscripciones/{item_id}", response_model=CircunscripcionOut)
async def update_circunscripcion(
    item_id: uuid.UUID,
    body: CircunscripcionUpdate,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> CircunscripcionOut:
    item = await service.update_circunscripcion(session, ctx, principal.user, item_id, body)
    return circ_out(item)


# --------------------------------------------------------------------------- registros


@router.get("/registros", response_model=Page[RegistroOut])
async def list_registros(
    _: CanRead,
    session: SessionDep,
    page: PageParamsDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    departamento: Annotated[str | None, Query(max_length=100)] = None,
    estado: EstadoRegistro | None = None,
) -> Page[RegistroOut]:
    items, total = await service.list_registros(
        session, page, query=q, departamento=departamento, estado=estado
    )
    cargos = await service.current_cargos_for_registros(session, [i.id for i in items])
    return Page(
        items=[registro_out(i, cargos[i.id]) for i in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/registros/{registro_id}", response_model=RegistroDetalle)
async def get_registro(registro_id: uuid.UUID, _: CanRead, session: SessionDep) -> RegistroDetalle:
    item = await service.get_registro(session, registro_id)
    return await registro_detalle(session, item)


async def registro_detalle(session: SessionDep, item: RegistroNotarial) -> RegistroDetalle:
    cargos = (await service.current_cargos_for_registros(session, [item.id]))[item.id]
    return RegistroDetalle(
        **registro_out(item, cargos).model_dump(),
        cargos_vigentes=[cargo_resumen(c) for c in cargos],
        domicilios=[
            DomicilioOut(
                id=d.id,
                domicilio=d.domicilio,
                fecha_desde=d.fecha_desde,
                fecha_hasta=d.fecha_hasta,
                cargado_por=email,
                created_at=d.created_at,
            )
            for d, email in await service.list_domicilios(session, item.id)
        ],
    )


@router.post("/registros", response_model=RegistroOut, status_code=201)
async def create_registro(
    body: RegistroIn, principal: CanWrite, session: SessionDep, ctx: RequestContextDep
) -> RegistroOut:
    return registro_out(await service.create_registro(session, ctx, principal.user, body), [])


@router.patch("/registros/{registro_id}", response_model=RegistroOut)
async def update_registro(
    registro_id: uuid.UUID,
    body: RegistroUpdate,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> RegistroOut:
    item = await service.update_registro(session, ctx, principal.user, registro_id, body)
    cargos = (await service.current_cargos_for_registros(session, [item.id]))[item.id]
    return registro_out(item, cargos)


@router.post("/registros/{registro_id}/domicilio", response_model=RegistroDetalle)
async def cambiar_domicilio(
    registro_id: uuid.UUID,
    body: DomicilioCambio,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> RegistroDetalle:
    """Nuevo domicilio del registro desde una fecha: el anterior queda en la historia."""
    item = await service.cambiar_domicilio(session, ctx, principal.user, registro_id, body)
    return await registro_detalle(session, item)


@router.post("/registros/{registro_id}/cierre", response_model=RegistroOut)
async def close_registro(
    registro_id: uuid.UUID,
    body: RegistroCierre,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> RegistroOut:
    item = await service.close_registro(session, ctx, principal.user, registro_id, body.motivo)
    return registro_out(item, [])


# --------------------------------------------------------------------------- escribanos


@router.get("/escribanos", response_model=Page[EscribanoOut])
async def list_escribanos(
    _: CanRead,
    session: SessionDep,
    page: PageParamsDep,
    q: Annotated[
        str | None,
        Query(
            max_length=100,
            description=(
                "Apellido, nombre, CUIT, DNI o matrícula. La matrícula no es única (el Colegio "
                "la reasigna): buscar por ella puede devolver varios escribanos."
            ),
        ),
    ] = None,
    estado: EstadoMatricula | None = None,
    registro_numero: Annotated[int | None, Query(gt=0)] = None,
    departamento: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[EscribanoOut]:
    items, total = await service.list_escribanos(
        session,
        page,
        query=q,
        estado=estado,
        registro_numero=registro_numero,
        departamento=departamento,
    )
    ids = [i.id for i in items]
    vigentes = await service.current_cargos_for_escribanos(session, ids)
    en_licencia = await licencias.vigentes(session, ids)
    return Page(
        items=[escribano_out(i, vigentes.get(i.id), en_licencia.get(i.id)) for i in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/escribanos/{escribano_id}", response_model=EscribanoDetalle)
async def get_escribano(
    escribano_id: uuid.UUID, _: CanRead, session: SessionDep
) -> EscribanoDetalle:
    return await escribano_detalle(session, await service.get_escribano(session, escribano_id))


@router.post("/escribanos", response_model=EscribanoDetalle, status_code=201)
async def create_escribano(
    body: EscribanoIn, principal: CanWrite, session: SessionDep, ctx: RequestContextDep
) -> EscribanoDetalle:
    item = await service.create_escribano(session, ctx, principal.user, body)
    return await escribano_detalle(session, item)


@router.patch("/escribanos/{escribano_id}", response_model=EscribanoDetalle)
async def update_escribano(
    escribano_id: uuid.UUID,
    body: EscribanoUpdate,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> EscribanoDetalle:
    item = await service.update_escribano(session, ctx, principal.user, escribano_id, body)
    return await escribano_detalle(session, item)


@router.post("/escribanos/{escribano_id}/completar", response_model=EscribanoDetalle)
async def completar_escribano(
    escribano_id: uuid.UUID,
    body: DatosACompletar,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> EscribanoDetalle:
    """Carga, una vez, los datos que faltaban (matrícula, fecha de juramento, CUIT, documento,
    primera escritura)."""
    item = await service.completar_escribano(session, ctx, principal.user, escribano_id, body)
    return await escribano_detalle(session, item)


@router.put("/escribanos/{escribano_id}/primera-escritura", response_model=EscribanoDetalle)
async def guardar_primera_escritura(
    escribano_id: uuid.UUID,
    body: PrimeraEscrituraIn,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> EscribanoDetalle:
    """Carga o corrige la primera escritura (corregirla exige motivo). Queda auditado."""
    item = await service.guardar_primera_escritura(session, ctx, principal.user, escribano_id, body)
    return await escribano_detalle(session, item)


@router.post(
    "/escribanos/{escribano_id}/licencias", response_model=EscribanoDetalle, status_code=201
)
async def iniciar_licencia(
    escribano_id: uuid.UUID,
    body: LicenciaIn,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> EscribanoDetalle:
    """Registra una licencia. No cambia el estado de la matrícula ni cierra su cargo."""
    await licencias.iniciar(session, ctx, principal.user, escribano_id, body)
    return await escribano_detalle(session, await service.get_escribano(session, escribano_id))


@router.post("/licencias/{licencia_id}/fin", response_model=EscribanoDetalle)
async def terminar_licencia(
    licencia_id: uuid.UUID,
    body: LicenciaFin,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> EscribanoDetalle:
    """Fija o adelanta la fecha de regreso de la licencia."""
    item = await licencias.terminar(session, ctx, principal.user, licencia_id, body)
    return await escribano_detalle(session, await service.get_escribano(session, item.escribano_id))


@router.post("/licencias/{licencia_id}/anulacion", response_model=EscribanoDetalle)
async def anular_licencia(
    licencia_id: uuid.UUID,
    body: LicenciaAnulacion,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> EscribanoDetalle:
    """Anula una licencia cargada por error (queda en la historia, con motivo)."""
    item = await licencias.anular(session, ctx, principal.user, licencia_id, body)
    return await escribano_detalle(session, await service.get_escribano(session, item.escribano_id))


@router.post("/escribanos/{escribano_id}/estado", response_model=EscribanoDetalle)
async def change_estado(
    escribano_id: uuid.UUID,
    body: EstadoCambio,
    principal: CanChangeStatus,
    session: SessionDep,
    ctx: RequestContextDep,
) -> EscribanoDetalle:
    item = await service.change_estado(session, ctx, principal.user, escribano_id, body)
    return await escribano_detalle(session, item)


@router.post("/escribanos/{escribano_id}/cargos", response_model=EscribanoDetalle, status_code=201)
async def assign_cargo(
    escribano_id: uuid.UUID,
    body: CargoAsignacion,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> EscribanoDetalle:
    await service.assign_cargo(session, ctx, principal.user, escribano_id, body)
    return await escribano_detalle(session, await service.get_escribano(session, escribano_id))


@router.post("/cargos/{cargo_id}/cierre", response_model=CargoOut)
async def close_cargo(
    cargo_id: uuid.UUID,
    body: CargoCierre,
    principal: CanWrite,
    session: SessionDep,
    ctx: RequestContextDep,
) -> CargoOut:
    return cargo_out(await service.close_cargo(session, ctx, principal.user, cargo_id, body))


@router.post("/escribanos/{escribano_id}/cuenta", response_model=EscribanoDetalle, status_code=201)
async def create_account(
    escribano_id: uuid.UUID,
    body: CuentaIn,
    principal: CanCreateAccount,
    background: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
    mailer: MailerDep,
) -> EscribanoDetalle:
    """Crea la cuenta de autogestión del escribano y le envía el enlace para definir la clave.

    Cuenta, vínculo y token se confirman juntos: si algo falla no queda una cuenta huérfana.
    """
    escribano = await service.get_escribano_for_update(session, escribano_id)
    if escribano.user_id is not None:
        raise ProblemError(HTTPStatus.CONFLICT, "El escribano ya tiene cuenta de autogestión.")
    persona = escribano.persona
    if not persona.cuit:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "Completá el CUIT del escribano antes de crearle la cuenta.",
        )
    if not persona.email:
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "Cargá el correo electrónico del escribano antes de crearle la cuenta.",
        )
    if str(body.email).lower() != persona.email.lower():
        raise ProblemError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "El correo confirmado no coincide con el registrado en el padrón.",
        )
    try:
        user, raw = await users_service.create_user(
            session,
            settings,
            ctx,
            principal.user,
            UserCreate(
                email=persona.email,
                full_name=f"{persona.nombre} {persona.apellido}",
                cuit=persona.cuit,
                roles=["ROLE_ESCRIBANO"],
            ),
            commit=False,
        )
        await service.link_account(session, ctx, principal.user, escribano, user)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    background.add_task(send_safely, mailer, account_created_mail(settings, user, raw))
    return await escribano_detalle(session, await service.get_escribano(session, escribano_id))
