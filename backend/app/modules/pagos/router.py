"""Endpoints de comprobantes y conciliación: /api/v1/pagos."""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Response, UploadFile

from app.common.deps import SessionDep, SettingsDep
from app.common.pagination import Page, PageParamsDep
from app.core.errors import ProblemError
from app.core.mail import send_safely
from app.modules.ddjj import service as ddjj_service
from app.modules.ddjj.models import Boleta
from app.modules.ddjj.router import registro_resumen
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import (
    Principal,
    RequestContextDep,
    require_any_permission,
    require_permissions,
)
from app.modules.iam.router_auth import MailerDep
from app.modules.padron.models import RegistroNotarial
from app.modules.pagos import mails, service, storage
from app.modules.pagos.catalog import EstadoComprobante, ResultadoConciliacion
from app.modules.pagos.models import Comprobante
from app.modules.pagos.schemas import (
    AprobacionIn,
    BoletaResumen,
    ComprobanteIn,
    ComprobanteOut,
    ConciliacionOut,
    RechazoIn,
)
from app.modules.parametros import service as parametros

router = APIRouter(prefix="/pagos", tags=["pagos"])

# Si el archivo se abre directo en el navegador: sin scripts ni recursos externos.
CSP_ARCHIVO = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"

CanUpload = Annotated[Principal, Depends(require_permissions(Perm.COMPROBANTES_UPLOAD))]
CanVerify = Annotated[Principal, Depends(require_permissions(Perm.COMPROBANTES_VERIFY))]
CanRead = Annotated[
    Principal,
    Depends(
        require_any_permission(
            Perm.BOLETAS_READ_OWN, Perm.BOLETAS_READ_ALL, Perm.COMPROBANTES_VERIFY
        )
    ),
]


async def comprobante_out(
    session: SessionDep, principal: Principal, c: Comprobante
) -> ComprobanteOut:
    boleta = await session.get(Boleta, c.boleta_id)
    registro = await session.get(RegistroNotarial, c.registro_id)
    assert boleta is not None and registro is not None  # noqa: S101 - FK RESTRICT
    conciliacion = await service.conciliacion_de(session, c.id)
    ver_personal = service.es_tesoreria(principal) or ddjj_service.ve_todo(principal)
    ids = {c.subido_por_user_id} | ({conciliacion.operador_user_id} if conciliacion else set())
    emails = await parametros.user_emails(session, ids)
    operador = None
    if conciliacion is not None:
        # Al escribano no se le muestran los correos del personal de la Caja.
        operador = emails.get(conciliacion.operador_user_id) if ver_personal else "Tesorería"
    return ComprobanteOut(
        id=c.id,
        boleta=BoletaResumen(
            id=boleta.id,
            numero=boleta.numero,
            ddjj_id=boleta.ddjj_id,
            registro=registro_resumen(registro),
            periodo=boleta.periodo,
            estado=boleta.estado,
            fecha_pago=boleta.fecha_pago,
            total_a_pagar=boleta.total_a_pagar,
        ),
        nombre_original=c.nombre_original,
        mime_type=c.mime_type,
        tamano_bytes=c.tamano_bytes,
        fecha_transferencia=c.fecha_transferencia,
        banco_origen=c.banco_origen,
        numero_operacion=c.numero_operacion,
        importe_declarado=c.importe_declarado,
        diferencia=c.importe_declarado - boleta.total_a_pagar,
        estado=EstadoComprobante(c.estado),
        motivo_rechazo=c.motivo_rechazo,
        subido_por=emails.get(c.subido_por_user_id),
        created_at=c.created_at,
        revisado_en=c.revisado_en,
        conciliacion=ConciliacionOut(
            resultado=ResultadoConciliacion(conciliacion.resultado),
            importe_confirmado=conciliacion.importe_confirmado,
            fecha_acreditacion=conciliacion.fecha_acreditacion,
            identificador_extracto=conciliacion.identificador_extracto,
            observaciones=conciliacion.observaciones,
            operador=operador,
            created_at=conciliacion.created_at,
        )
        if conciliacion
        else None,
    )


@router.post("/boletas/{boleta_id}/comprobantes", response_model=ComprobanteOut, status_code=201)
async def subir_comprobante(
    boleta_id: uuid.UUID,
    datos: Annotated[ComprobanteIn, Form()],
    archivo: Annotated[UploadFile, File(description="PDF, PNG o JPG de hasta 10 MB")],
    principal: CanUpload,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> ComprobanteOut:
    """Adjunta el comprobante de una transferencia. Queda en revisión: no es un pago."""
    try:
        validado = await storage.validar(archivo, settings.max_upload_bytes)
    except storage.ArchivoInvalidoError as exc:
        raise ProblemError(exc.status, str(exc), type_="urn:suite-notarial:pagos:archivo") from exc
    item = await service.subir(session, settings, ctx, principal, boleta_id, datos, validado)
    return await comprobante_out(session, principal, item)


@router.get("/boletas/{boleta_id}/comprobantes", response_model=list[ComprobanteOut])
async def comprobantes_de_boleta(
    boleta_id: uuid.UUID, principal: CanRead, session: SessionDep
) -> list[ComprobanteOut]:
    if not service.es_tesoreria(principal):
        await ddjj_service.get_boleta(session, principal, boleta_id)
    return [
        await comprobante_out(session, principal, c)
        for c in await service.de_boleta(session, boleta_id)
    ]


@router.get("/comprobantes", response_model=Page[ComprobanteOut])
async def mesa_de_conciliacion(
    principal: CanVerify,
    session: SessionDep,
    page: PageParamsDep,
    estado: EstadoComprobante | None = EstadoComprobante.PENDIENTE_REVISION,
) -> Page[ComprobanteOut]:
    """Bandeja de Tesorería. Por defecto, los comprobantes en revisión por orden de llegada."""
    items, total = await service.mesa(session, estado, page)
    return Page(
        items=[await comprobante_out(session, principal, c) for c in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/comprobantes/{comprobante_id}", response_model=ComprobanteOut)
async def get_comprobante(
    comprobante_id: uuid.UUID, principal: CanRead, session: SessionDep
) -> ComprobanteOut:
    item = await service.get(session, principal, comprobante_id)
    return await comprobante_out(session, principal, item)


@router.get(
    "/comprobantes/{comprobante_id}/archivo",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}, "image/png": {}, "image/jpeg": {}}}},
)
async def archivo_comprobante(
    comprobante_id: uuid.UUID,
    principal: CanRead,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> Response:
    item = await service.get(session, principal, comprobante_id)
    contenido = await service.archivo(session, settings, ctx, principal.user, item)
    extension = item.archivo.rsplit(".", 1)[-1]
    return Response(
        content=contenido,
        media_type=item.mime_type,
        headers={
            # El nombre lo arma el servidor: nunca se refleja el nombre que subió el usuario.
            "Content-Disposition": f'inline; filename="comprobante-{item.id.hex[:8]}.{extension}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": CSP_ARCHIVO,
        },
    )


@router.post("/comprobantes/{comprobante_id}/aprobar", response_model=ComprobanteOut)
async def aprobar(
    comprobante_id: uuid.UUID,
    body: AprobacionIn,
    principal: CanVerify,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
    mailer: MailerDep,
    background: BackgroundTasks,
) -> ComprobanteOut:
    """Confirma el pago contra el extracto: el comprobante queda aprobado y la boleta, pagada."""
    r = await service.aprobar(session, ctx, principal, comprobante_id, body)
    if r.destinatario is not None:
        mail = mails.comprobante_aprobado_mail(settings, r.destinatario, r.boleta)
        background.add_task(send_safely, mailer, mail)
    return await comprobante_out(session, principal, r.comprobante)


@router.post("/comprobantes/{comprobante_id}/rechazar", response_model=ComprobanteOut)
async def rechazar(
    comprobante_id: uuid.UUID,
    body: RechazoIn,
    principal: CanVerify,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
    mailer: MailerDep,
    background: BackgroundTasks,
) -> ComprobanteOut:
    """Rechaza con motivo y avisa al escribano; la boleta sigue pendiente."""
    r = await service.rechazar(session, ctx, principal, comprobante_id, body.motivo)
    if r.destinatario is not None:
        mail = mails.comprobante_rechazado_mail(settings, r.destinatario, r.boleta, body.motivo)
        background.add_task(send_safely, mailer, mail)
    return await comprobante_out(session, principal, r.comprobante)
