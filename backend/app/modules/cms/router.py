"""Sitio institucional: administración (/api/v1/cms) y lectura pública (/api/v1/publico)."""

import uuid
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Path, Request, Response, UploadFile

from app.common.deps import SessionDep, SettingsDep
from app.common.pagination import Page, PageParams, PageParamsDep
from app.core.config import Settings
from app.core.errors import ProblemError
from app.modules.cms import pdf, service
from app.modules.cms.catalog import TIPO_DOCUMENTO_TEXTO, EstadoPublicacion, TipoDocumento
from app.modules.cms.models import Autoridad, Documento, DocumentoVersion, Novedad
from app.modules.cms.schemas import (
    AutoridadIn,
    AutoridadOut,
    AutoridadUpdate,
    DocumentoIn,
    DocumentoOut,
    DocumentoPublico,
    DocumentoUpdate,
    EstadoIn,
    Motivo,
    NovedadIn,
    NovedadOut,
    NovedadPublica,
    NovedadResumen,
    SitioPublico,
    VersionOut,
    VersionPublica,
)
from app.modules.iam.catalog import Perm
from app.modules.iam.deps import Principal, RequestContextDep, require_permissions
from app.modules.pagos.storage import ArchivoInvalidoError, ArchivoValidado
from app.modules.parametros import service as parametros

router = APIRouter(prefix="/cms", tags=["cms"])
public_router = APIRouter(prefix="/publico", tags=["sitio público"])

CanPublish = Annotated[Principal, Depends(require_permissions(Perm.CMS_PUBLISH))]
SlugPath = Annotated[str, Path(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=150)]

# Contenido público: sin datos de sesión. Los listados se guardan un minuto. Los PDF se revalidan
# siempre (ETag = huella, 304 si no cambió): el canónico puede pasar a una versión nueva y
# cualquier documento puede archivarse, así que ninguna caché debe seguir sirviéndolo.
CACHE_PUBLICO = "public, max-age=60, stale-while-revalidate=300"
CACHE_PDF = "public, no-cache"


def documento_url(settings: Settings, slug: str, version: int | None = None) -> str:
    """URL canónica permanente (SEC-04: siempre desde PUBLIC_WEB_URL)."""
    base = f"{settings.public_web_base}/api/v1/publico/documentos/{slug}"
    return f"{base}.pdf" if version is None else f"{base}/v{version}.pdf"


def autoridad_out(a: Autoridad) -> AutoridadOut:
    return AutoridadOut(
        id=a.id,
        cargo=a.cargo,
        nombre=a.nombre,
        orden=a.orden,
        mandato_desde=a.mandato_desde,
        mandato_hasta=a.mandato_hasta,
        is_active=a.is_active,
    )


async def novedad_out(session: SessionDep, n: Novedad) -> NovedadOut:
    emails = await parametros.user_emails(session, {n.autor_user_id})
    return NovedadOut(
        id=n.id,
        slug=n.slug,
        titulo=n.titulo,
        resumen=n.resumen,
        contenido=n.contenido,
        estado=EstadoPublicacion(n.estado),
        fecha_publicacion=n.fecha_publicacion,
        autor=emails.get(n.autor_user_id),
        created_at=n.created_at,
        updated_at=n.updated_at,
    )


def novedad_resumen(n: Novedad) -> NovedadResumen:
    assert n.fecha_publicacion is not None  # noqa: S101 - CHECK publicada_con_fecha
    return NovedadResumen(
        slug=n.slug, titulo=n.titulo, resumen=n.resumen, fecha_publicacion=n.fecha_publicacion
    )


def version_out(
    settings: Settings,
    d: Documento,
    v: DocumentoVersion,
    emails: dict[uuid.UUID, str],
    integra: bool | None = None,
) -> VersionOut:
    return VersionOut(
        version=v.version,
        nombre_original=v.nombre_original,
        sha256=v.sha256,
        tamano_bytes=v.tamano_bytes,
        paginas=v.paginas,
        motivo=v.motivo,
        subido_por=emails.get(v.subido_por_user_id),
        created_at=v.created_at,
        url=documento_url(settings, d.slug, v.version),
        integra=integra,
    )


async def documento_out(
    session: SessionDep, settings: Settings, d: Documento, *, verificar: bool
) -> DocumentoOut:
    vs = await service.versiones(session, d.id)
    emails = await parametros.user_emails(session, {v.subido_por_user_id for v in vs})
    return DocumentoOut(
        id=d.id,
        slug=d.slug,
        tipo=TipoDocumento(d.tipo),
        ejercicio=d.ejercicio,
        titulo=d.titulo,
        descripcion=d.descripcion,
        estado=EstadoPublicacion(d.estado),
        fecha_publicacion=d.fecha_publicacion,
        url=documento_url(settings, d.slug),
        versiones=[
            version_out(
                settings, d, v, emails, await service.verificar(settings, v) if verificar else None
            )
            for v in vs
        ],
    )


async def documento_publico(
    session: SessionDep, settings: Settings, d: Documento
) -> DocumentoPublico:
    assert d.fecha_publicacion is not None  # noqa: S101 - se fija al publicar
    vs = await service.versiones_publicas(session, d)
    vigente = vs[0]
    tipo = TipoDocumento(d.tipo)
    return DocumentoPublico(
        slug=d.slug,
        tipo=tipo,
        tipo_texto=TIPO_DOCUMENTO_TEXTO[tipo],
        ejercicio=d.ejercicio,
        titulo=d.titulo,
        descripcion=d.descripcion,
        fecha_publicacion=d.fecha_publicacion,
        url=documento_url(settings, d.slug),
        paginas=vigente.paginas,
        tamano_bytes=vigente.tamano_bytes,
        sha256=vigente.sha256,
        version=vigente.version,
        actualizado=vigente.created_at,
        motivo_actualizacion=vigente.motivo if len(vs) > 1 else None,
        versiones_anteriores=[
            VersionPublica(
                version=v.version,
                sha256=v.sha256,
                tamano_bytes=v.tamano_bytes,
                paginas=v.paginas,
                motivo=v.motivo,
                created_at=v.created_at,
                url=documento_url(settings, d.slug, v.version),
            )
            for v in vs[1:]
        ],
    )


async def _pdf(file: UploadFile, settings: Settings) -> tuple[ArchivoValidado, int]:
    try:
        return await pdf.validar_pdf(file, settings.CMS_MAX_DOC_MB * 1024 * 1024)
    except ArchivoInvalidoError as exc:
        raise ProblemError(exc.status, str(exc), type_="urn:suite-notarial:cms:pdf") from exc


# --------------------------------------------------------------------------- administración


@router.get("/autoridades", response_model=list[AutoridadOut])
async def list_autoridades(_: CanPublish, session: SessionDep) -> list[AutoridadOut]:
    return [autoridad_out(a) for a in await service.list_autoridades(session, solo_activas=False)]


@router.post("/autoridades", response_model=AutoridadOut, status_code=201)
async def crear_autoridad(
    body: AutoridadIn, principal: CanPublish, session: SessionDep, ctx: RequestContextDep
) -> AutoridadOut:
    return autoridad_out(await service.crear_autoridad(session, ctx, principal.user, body))


@router.put("/autoridades/{autoridad_id}", response_model=AutoridadOut)
async def actualizar_autoridad(
    autoridad_id: uuid.UUID,
    body: AutoridadUpdate,
    principal: CanPublish,
    session: SessionDep,
    ctx: RequestContextDep,
) -> AutoridadOut:
    item = await service.actualizar_autoridad(session, ctx, principal.user, autoridad_id, body)
    return autoridad_out(item)


@router.get("/novedades", response_model=Page[NovedadOut])
async def list_novedades(
    _: CanPublish,
    session: SessionDep,
    page: PageParamsDep,
    estado: EstadoPublicacion | None = None,
) -> Page[NovedadOut]:
    items, total = await service.list_novedades(session, estado, page)
    return Page(
        items=[await novedad_out(session, n) for n in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/novedades/{novedad_id}", response_model=NovedadOut)
async def get_novedad(novedad_id: uuid.UUID, _: CanPublish, session: SessionDep) -> NovedadOut:
    return await novedad_out(session, await service.get_novedad(session, novedad_id))


@router.post("/novedades", response_model=NovedadOut, status_code=201)
async def crear_novedad(
    body: NovedadIn, principal: CanPublish, session: SessionDep, ctx: RequestContextDep
) -> NovedadOut:
    item = await service.crear_novedad(session, ctx, principal.user, body)
    return await novedad_out(session, item)


@router.put("/novedades/{novedad_id}", response_model=NovedadOut)
async def actualizar_novedad(
    novedad_id: uuid.UUID,
    body: NovedadIn,
    principal: CanPublish,
    session: SessionDep,
    ctx: RequestContextDep,
) -> NovedadOut:
    item = await service.actualizar_novedad(session, ctx, principal.user, novedad_id, body)
    return await novedad_out(session, item)


@router.post("/novedades/{novedad_id}/estado", response_model=NovedadOut)
async def estado_novedad(
    novedad_id: uuid.UUID,
    body: EstadoIn,
    principal: CanPublish,
    session: SessionDep,
    ctx: RequestContextDep,
) -> NovedadOut:
    item = await service.estado_novedad(session, ctx, principal.user, novedad_id, body.estado)
    return await novedad_out(session, item)


@router.get("/documentos", response_model=list[DocumentoOut])
async def list_documentos(
    _: CanPublish, session: SessionDep, settings: SettingsDep
) -> list[DocumentoOut]:
    return [
        await documento_out(session, settings, d, verificar=False)
        for d in await service.list_documentos(session, solo_publicados=False)
    ]


@router.get("/documentos/{documento_id}", response_model=DocumentoOut)
async def get_documento(
    documento_id: uuid.UUID, _: CanPublish, session: SessionDep, settings: SettingsDep
) -> DocumentoOut:
    """Detalle con la verificación de huella de cada versión guardada."""
    item = await service.get_documento(session, documento_id)
    return await documento_out(session, settings, item, verificar=True)


@router.post("/documentos", response_model=DocumentoOut, status_code=201)
async def crear_documento(
    datos: Annotated[DocumentoIn, Form()],
    archivo: Annotated[UploadFile, File(description="PDF")],
    principal: CanPublish,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> DocumentoOut:
    validado, paginas = await _pdf(archivo, settings)
    item = await service.crear_documento(
        session, settings, ctx, principal.user, datos, validado, paginas
    )
    return await documento_out(session, settings, item, verificar=False)


@router.post("/documentos/{documento_id}/versiones", response_model=DocumentoOut, status_code=201)
async def nueva_version(
    documento_id: uuid.UUID,
    motivo: Annotated[Motivo, Form()],
    archivo: Annotated[UploadFile, File(description="PDF")],
    principal: CanPublish,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> DocumentoOut:
    """Reemplaza el archivo conservando el enlace permanente y el histórico."""
    validado, paginas = await _pdf(archivo, settings)
    item = await service.nueva_version(
        session, settings, ctx, principal.user, documento_id, validado, paginas, motivo
    )
    return await documento_out(session, settings, item, verificar=False)


@router.put("/documentos/{documento_id}", response_model=DocumentoOut)
async def actualizar_documento(
    documento_id: uuid.UUID,
    body: DocumentoUpdate,
    principal: CanPublish,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> DocumentoOut:
    item = await service.actualizar_documento(session, ctx, principal.user, documento_id, body)
    return await documento_out(session, settings, item, verificar=False)


@router.post("/documentos/{documento_id}/estado", response_model=DocumentoOut)
async def estado_documento(
    documento_id: uuid.UUID,
    body: EstadoIn,
    principal: CanPublish,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> DocumentoOut:
    item = await service.estado_documento(session, ctx, principal.user, documento_id, body.estado)
    return await documento_out(session, settings, item, verificar=False)


# --------------------------------------------------------------------------- sitio público


@public_router.get("/sitio", response_model=SitioPublico)
async def sitio(response: Response, session: SessionDep, settings: SettingsDep) -> SitioPublico:
    """Portada: autoridades vigentes, últimas novedades y documentos publicados."""
    novedades, _ = await service.novedades_publicadas(session, PageParams(page=1, page_size=3))
    response.headers["Cache-Control"] = CACHE_PUBLICO
    return SitioPublico(
        autoridades=[
            autoridad_out(a) for a in await service.list_autoridades(session, solo_activas=True)
        ],
        novedades=[novedad_resumen(n) for n in novedades],
        documentos=[
            await documento_publico(session, settings, d)
            for d in await service.list_documentos(session, solo_publicados=True)
        ],
    )


@public_router.get("/novedades", response_model=Page[NovedadResumen])
async def novedades(
    response: Response, session: SessionDep, page: PageParamsDep
) -> Page[NovedadResumen]:
    items, total = await service.novedades_publicadas(session, page)
    response.headers["Cache-Control"] = CACHE_PUBLICO
    return Page(
        items=[novedad_resumen(n) for n in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@public_router.get("/novedades/{slug}", response_model=NovedadPublica)
async def novedad(slug: SlugPath, response: Response, session: SessionDep) -> NovedadPublica:
    n = await service.novedad_publicada(session, slug)
    response.headers["Cache-Control"] = CACHE_PUBLICO
    return NovedadPublica(**novedad_resumen(n).model_dump(), contenido=n.contenido)


async def _servir_pdf(
    request: Request,
    session: SessionDep,
    settings: Settings,
    ctx: RequestContextDep,
    slug: str,
    version: int | None,
) -> Response:
    d = await service.documento_publicado(session, slug)
    vs = await service.versiones_publicas(session, d)
    elegida = vs[0] if version is None else next((v for v in vs if v.version == version), None)
    if elegida is None:
        raise ProblemError(HTTPStatus.NOT_FOUND, "Esa versión del documento no existe.")
    etag = f'"{elegida.sha256}"'
    cache = CACHE_PDF
    # El cliente ya tiene exactamente este archivo (misma huella): no se reenvía.
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cache})
    contenido = await service.contenido_verificado(session, settings, ctx, d, elegida)
    nombre = d.slug if version is None else f"{d.slug}-v{elegida.version}"
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{nombre}.pdf"',
            "Cache-Control": cache,
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )


PDF_RESPONSES: dict[int | str, dict[str, Any]] = {200: {"content": {"application/pdf": {}}}}


@public_router.get("/documentos/{slug}.pdf", response_class=Response, responses=PDF_RESPONSES)
async def descargar_documento(
    slug: SlugPath,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> Response:
    """Enlace permanente: siempre la última versión, verificada contra su huella."""
    return await _servir_pdf(request, session, settings, ctx, slug, None)


@public_router.get(
    "/documentos/{slug}/v{version}.pdf", response_class=Response, responses=PDF_RESPONSES
)
async def descargar_version(
    slug: SlugPath,
    request: Request,
    version: Annotated[int, Path(ge=1, le=10_000)],
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> Response:
    return await _servir_pdf(request, session, settings, ctx, slug, version)
