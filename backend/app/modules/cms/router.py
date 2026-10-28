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
from app.modules.cms import sitio as sitio_svc
from app.modules.cms.catalog import (
    GRUPO_PAGINA_TEXTO,
    SECCION_NOVEDAD_TEXTO,
    TIPO_DOCUMENTO_TEXTO,
    EstadoPublicacion,
    GrupoPagina,
    SeccionNovedad,
    TipoDocumento,
)
from app.modules.cms.models import Autoridad, Documento, DocumentoVersion, Novedad, Pagina
from app.modules.cms.schemas import (
    AutoridadIn,
    AutoridadOut,
    AutoridadUpdate,
    Contacto,
    DocumentoIn,
    DocumentoOut,
    DocumentoPublico,
    DocumentoUpdate,
    EstadoIn,
    FilaPublica,
    Motivo,
    NovedadIn,
    NovedadOut,
    NovedadPublica,
    NovedadResumen,
    PaginaIn,
    PaginaMenu,
    PaginaOut,
    PaginaPublica,
    PortadaIn,
    PortadaOut,
    PortadaPublica,
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

# Contenido público: sin datos de sesión. Portada, listados y páginas se piden de nuevo cada vez:
# lo que la Caja publica, archiva o reacomoda en la portada se ve al instante (con caché, quien
# edita vería la versión anterior y creería que no se guardó). Los PDF se revalidan siempre
# (ETag = huella, 304 si no cambió): el canónico puede pasar a una versión nueva y cualquier
# documento puede archivarse, así que ninguna caché debe seguir sirviéndolo.
CACHE_PUBLICO = "public, no-cache"
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


def _version_imagen(n: Novedad) -> str:
    # La huella en la URL permite cachear la imagen para siempre: si cambia, cambia la URL.
    assert n.imagen_sha256 is not None  # noqa: S101 - solo se llama con imagen
    return n.imagen_sha256[:16]


async def novedad_out(session: SessionDep, n: Novedad) -> NovedadOut:
    emails = await parametros.user_emails(session, {n.autor_user_id})
    return NovedadOut(
        id=n.id,
        slug=n.slug,
        titulo=n.titulo,
        resumen=n.resumen,
        contenido=n.contenido,
        seccion=SeccionNovedad(n.seccion),
        estado=EstadoPublicacion(n.estado),
        fecha_publicacion=n.fecha_publicacion,
        imagen_url=(
            f"/api/v1/cms/novedades/{n.id}/imagen?v={_version_imagen(n)}" if n.imagen_ruta else None
        ),
        imagen_alt=n.imagen_alt,
        autor=emails.get(n.autor_user_id),
        created_at=n.created_at,
        updated_at=n.updated_at,
    )


def novedad_resumen(n: Novedad) -> NovedadResumen:
    assert n.fecha_publicacion is not None  # noqa: S101 - CHECK publicada_con_fecha
    seccion = SeccionNovedad(n.seccion)
    return NovedadResumen(
        slug=n.slug,
        titulo=n.titulo,
        resumen=n.resumen,
        seccion=seccion,
        seccion_texto=SECCION_NOVEDAD_TEXTO[seccion],
        fecha_publicacion=n.fecha_publicacion,
        imagen_url=(
            f"/api/v1/publico/novedades/{n.slug}/imagen?v={_version_imagen(n)}"
            if n.imagen_ruta
            else None
        ),
        imagen_alt=n.imagen_alt,
    )


def pagina_out(p: Pagina) -> PaginaOut:
    return PaginaOut(
        id=p.id,
        slug=p.slug,
        grupo=GrupoPagina(p.grupo),
        titulo=p.titulo,
        contenido=p.contenido,
        orden=p.orden,
        estado=EstadoPublicacion(p.estado),
        updated_at=p.updated_at,
    )


def _imagen_problem(exc: ArchivoInvalidoError) -> ProblemError:
    return ProblemError(exc.status, str(exc), type_="urn:suite-notarial:cms:imagen")


def _servir_imagen(n: Novedad, contenido: bytes, cache: str) -> Response:
    assert n.imagen_mime is not None  # noqa: S101 - CHECK imagen_completa
    return Response(
        content=contenido,
        media_type=n.imagen_mime,
        headers={
            "Cache-Control": cache,
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
        },
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


@router.post("/novedades/{novedad_id}/imagen", response_model=NovedadOut)
async def poner_imagen(
    novedad_id: uuid.UUID,
    alt: Annotated[str, Form(min_length=3, max_length=200)],
    archivo: Annotated[UploadFile, File(description="JPG, PNG o WEBP")],
    principal: CanPublish,
    session: SessionDep,
    settings: SettingsDep,
    ctx: RequestContextDep,
) -> NovedadOut:
    """Imagen principal de la nota (reemplaza la anterior). `alt`: qué muestra la imagen."""
    try:
        validada = await sitio_svc.validar_imagen(archivo)
    except ArchivoInvalidoError as exc:
        raise _imagen_problem(exc) from exc
    item = await sitio_svc.poner_imagen(
        session, settings, ctx, principal.user, novedad_id, validada, alt.strip()
    )
    return await novedad_out(session, item)


@router.post("/novedades/{novedad_id}/imagen/quitar", response_model=NovedadOut)
async def quitar_imagen(
    novedad_id: uuid.UUID, principal: CanPublish, session: SessionDep, ctx: RequestContextDep
) -> NovedadOut:
    item = await sitio_svc.quitar_imagen(session, ctx, principal.user, novedad_id)
    return await novedad_out(session, item)


@router.get("/novedades/{novedad_id}/imagen", response_class=Response)
async def imagen_admin(
    novedad_id: uuid.UUID, _: CanPublish, session: SessionDep, settings: SettingsDep
) -> Response:
    """La imagen también en borrador, para verla antes de publicar."""
    item = await service.get_novedad(session, novedad_id)
    contenido = await sitio_svc.contenido_imagen(settings, item)
    return _servir_imagen(item, contenido, "private, max-age=3600")


@router.get("/paginas", response_model=list[PaginaOut])
async def list_paginas(_: CanPublish, session: SessionDep) -> list[PaginaOut]:
    return [pagina_out(p) for p in await sitio_svc.list_paginas(session, solo_publicadas=False)]


@router.post("/paginas", response_model=PaginaOut, status_code=201)
async def crear_pagina(
    body: PaginaIn, principal: CanPublish, session: SessionDep, ctx: RequestContextDep
) -> PaginaOut:
    return pagina_out(await sitio_svc.crear_pagina(session, ctx, principal.user, body))


@router.put("/paginas/{pagina_id}", response_model=PaginaOut)
async def actualizar_pagina(
    pagina_id: uuid.UUID,
    body: PaginaIn,
    principal: CanPublish,
    session: SessionDep,
    ctx: RequestContextDep,
) -> PaginaOut:
    item = await sitio_svc.actualizar_pagina(session, ctx, principal.user, pagina_id, body)
    return pagina_out(item)


@router.post("/paginas/{pagina_id}/estado", response_model=PaginaOut)
async def estado_pagina(
    pagina_id: uuid.UUID,
    body: EstadoIn,
    principal: CanPublish,
    session: SessionDep,
    ctx: RequestContextDep,
) -> PaginaOut:
    item = await sitio_svc.estado_pagina(session, ctx, principal.user, pagina_id, body.estado)
    return pagina_out(item)


@router.get("/portada", response_model=PortadaOut)
async def get_portada(_: CanPublish, session: SessionDep) -> PortadaOut:
    vigente = await sitio_svc.portada_vigente(session)
    if vigente is None:
        return PortadaOut(destacadas=[], filas=[], actualizada=None, actualizada_por=None)
    emails = await parametros.user_emails(session, {vigente.creado_por_user_id})
    config = sitio_svc.leer_configuracion(vigente.configuracion)
    return PortadaOut(
        destacadas=config.destacadas,
        filas=config.filas,
        actualizada=vigente.created_at,
        actualizada_por=emails.get(vigente.creado_por_user_id),
    )


@router.put("/portada", response_model=PortadaOut)
async def guardar_portada(
    body: PortadaIn, principal: CanPublish, session: SessionDep, ctx: RequestContextDep
) -> PortadaOut:
    nueva = await sitio_svc.guardar_portada(session, ctx, principal.user, body)
    return PortadaOut(
        destacadas=body.destacadas,
        filas=body.filas,
        actualizada=nueva.created_at,
        actualizada_por=principal.user.email,
    )


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


async def _portada_publica(session: SessionDep) -> PortadaPublica:
    """La portada armada por la Caja, solo con notas publicadas. Sin armado guardado, la nota
    más reciente va destacada y las siguientes en filas automáticas."""
    vigente = await sitio_svc.portada_vigente(session)
    if vigente is None:
        recientes, _ = await service.novedades_publicadas(session, PageParams(page=1, page_size=9))
        resumenes = [novedad_resumen(n) for n in recientes]
        filas: list[FilaPublica] = []
        resto = resumenes[1:]
        for distribucion, cantidad in (("2+1+1", 3), ("1+1+1+1", 4), ("2+2", 2)):
            if not resto:
                break
            tramo, resto = resto[:cantidad], resto[cantidad:]
            filas.append(FilaPublica.model_validate({"distribucion": distribucion, "notas": tramo}))
        return PortadaPublica(destacadas=resumenes[:1], filas=filas)
    config = sitio_svc.leer_configuracion(vigente.configuracion)
    ids = set(config.destacadas) | {n for f in config.filas for n in f.notas if n}
    notas = await sitio_svc.novedades_por_id(session, ids, solo_publicadas=True)
    return PortadaPublica(
        destacadas=[novedad_resumen(notas[i]) for i in config.destacadas if i in notas],
        filas=[
            FilaPublica(
                distribucion=f.distribucion,
                notas=[novedad_resumen(notas[i]) for i in f.notas if i and i in notas],
            )
            for f in config.filas
            # Una fila sin ninguna nota publicada no se muestra.
            if any(i and i in notas for i in f.notas)
        ],
    )


@public_router.get("/sitio", response_model=SitioPublico)
async def sitio(response: Response, session: SessionDep, settings: SettingsDep) -> SitioPublico:
    """Portada: armado editorial, menú, contacto, autoridades, últimas novedades y documentos."""
    novedades, _ = await service.novedades_publicadas(session, PageParams(page=1, page_size=6))
    response.headers["Cache-Control"] = CACHE_PUBLICO
    return SitioPublico(
        portada=await _portada_publica(session),
        menu=[
            PaginaMenu(slug=p.slug, grupo=GrupoPagina(p.grupo), titulo=p.titulo)
            for p in await sitio_svc.list_paginas(session, solo_publicadas=True)
        ],
        contacto=Contacto(
            nombre=settings.CAJA_NOMBRE,
            domicilio=settings.CAJA_DOMICILIO,
            telefono=settings.CAJA_TELEFONO,
            email=settings.CAJA_EMAIL,
        ),
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
    response: Response,
    session: SessionDep,
    page: PageParamsDep,
    seccion: SeccionNovedad | None = None,
) -> Page[NovedadResumen]:
    items, total = await service.novedades_publicadas(session, page, seccion)
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


@public_router.get("/novedades/{slug}/imagen", response_class=Response)
async def imagen_publica(slug: SlugPath, session: SessionDep, settings: SettingsDep) -> Response:
    n = await service.novedad_publicada(session, slug)
    contenido = await sitio_svc.contenido_imagen(settings, n)
    # La URL lleva la huella (?v=): una imagen nueva es otra URL, así que esta no cambia nunca.
    return _servir_imagen(n, contenido, "public, max-age=31536000, immutable")


@public_router.get("/paginas/{slug}", response_model=PaginaPublica)
async def pagina(slug: SlugPath, response: Response, session: SessionDep) -> PaginaPublica:
    p = await sitio_svc.pagina_publicada(session, slug)
    response.headers["Cache-Control"] = CACHE_PUBLICO
    grupo = GrupoPagina(p.grupo)
    return PaginaPublica(
        slug=p.slug,
        grupo=grupo,
        grupo_texto=GRUPO_PAGINA_TEXTO[grupo],
        titulo=p.titulo,
        contenido=p.contenido,
        updated_at=p.updated_at,
    )


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
