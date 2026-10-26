"""Sitio institucional: publicación auditada, PDFs válidos e integridad verificada al servir."""

import io
import warnings
from collections.abc import AsyncIterator
from typing import Any

import anyio
import pyotp
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pypdf import PdfWriter
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.core.config import get_settings
from app.modules.cms.models import DocumentoVersion
from app.modules.pagos.storage import upload_root
from tests.ddjj.conftest import _client
from tests.iam.factories import make_user
from tests.iam.test_rbac import login


def pdf(paginas: int = 2, *, js: bool = False, clave: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(paginas):
        writer.add_blank_page(width=595, height=842)
    if js:
        # Solo para fabricar el caso malicioso: pypdf avisa que la API cambiará en la 7.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            writer.add_js("app.alert('hola');")
    if clave:
        writer.encrypt(clave)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
async def editor(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Administración de Caja: cms:publish, con 2FA."""
    secret = pyotp.random_base32()
    user = await make_user(db_session, roles=("ROLE_CAJA",), totp_secret=secret)
    async with await _client(app) as ac:
        await login(ac, user, secret)
        yield ac


async def subir(
    client: AsyncClient,
    contenido: bytes,
    *,
    titulo: str = "Estados contables",
    ejercicio: int = 2025,
    nombre: str = "eecc.pdf",
) -> Any:
    return await client.post(
        "/api/v1/cms/documentos",
        data={"tipo": "ESTADO_CONTABLE", "ejercicio": str(ejercicio), "titulo": titulo},
        files={"archivo": (nombre, contenido, "application/pdf")},
    )


async def _eventos(db_session: AsyncSession) -> set[str]:
    return set((await db_session.scalars(select(AuditSecurityLog.event_type))).all())


async def test_documento_borrador_publicado_y_versionado(
    editor: AsyncClient, client: AsyncClient, db_session: AsyncSession
) -> None:
    original = pdf(3)
    creado = await subir(editor, original)
    assert creado.status_code == 201, creado.text
    doc = creado.json()
    assert doc["slug"] == "estados-contables-2025"
    assert doc["estado"] == "BORRADOR"
    assert doc["url"] == (
        "https://suite.cajanotarial-sj.test/api/v1/publico/documentos/estados-contables-2025.pdf"
    )
    canonica = "/api/v1/publico/documentos/estados-contables-2025.pdf"

    # Borrador: no existe para el público.
    assert (await client.get(canonica)).status_code == 404
    publicado = await editor.post(
        f"/api/v1/cms/documentos/{doc['id']}/estado", json={"estado": "PUBLICADO"}
    )
    assert publicado.status_code == 200
    r1 = await client.get(canonica)
    assert r1.status_code == 200
    assert r1.content == original
    assert r1.headers["content-type"] == "application/pdf"
    assert r1.headers["cache-control"].startswith("public")
    assert r1.headers["etag"] == f'"{doc["versiones"][0]["sha256"]}"'

    # Reemplazar no rompe el enlace: la canónica sirve la nueva y la v1 queda en el histórico.
    nuevo = pdf(4)
    sin_motivo = await editor.post(
        f"/api/v1/cms/documentos/{doc['id']}/versiones",
        data={"motivo": "x"},
        files={"archivo": ("v2.pdf", nuevo, "application/pdf")},
    )
    identico = await editor.post(
        f"/api/v1/cms/documentos/{doc['id']}/versiones",
        data={"motivo": "Mismo archivo"},
        files={"archivo": ("v1.pdf", original, "application/pdf")},
    )
    v2 = await editor.post(
        f"/api/v1/cms/documentos/{doc['id']}/versiones",
        data={"motivo": "Corrección de la nota 4"},
        files={"archivo": ("v2.pdf", nuevo, "application/pdf")},
    )
    assert sin_motivo.status_code == 422
    assert identico.status_code == 409
    assert v2.status_code == 201
    assert (await client.get(canonica)).content == nuevo
    v1 = await client.get("/api/v1/publico/documentos/estados-contables-2025/v1.pdf")
    assert v1.content == original

    sitio = (await client.get("/api/v1/publico/sitio")).json()
    publico = sitio["documentos"][0]
    assert publico["version"] == 2 and publico["paginas"] == 4
    assert [v["version"] for v in publico["versiones_anteriores"]] == [1]
    # Sin metadatos internos en el sitio público.
    assert "subido_por" not in publico["versiones_anteriores"][0]
    assert "nombre_original" not in publico["versiones_anteriores"][0]
    assert {"CMS_DOCUMENTO_CREADO", "CMS_DOCUMENTO_ESTADO", "CMS_DOCUMENTO_VERSION"} <= (
        await _eventos(db_session)
    )

    archivado = await editor.post(
        f"/api/v1/cms/documentos/{doc['id']}/estado", json={"estado": "ARCHIVADO"}
    )
    assert archivado.status_code == 200
    assert (await client.get(canonica)).status_code == 404
    volver_a_borrador = await editor.post(
        f"/api/v1/cms/documentos/{doc['id']}/estado", json={"estado": "BORRADOR"}
    )
    assert volver_a_borrador.status_code == 409


@pytest.mark.parametrize(
    ("contenido", "status"),
    [
        (b"<html><body>Error 404</body></html>", 415),  # la página HTML disfrazada de .pdf
        (b"MZ\x90\x00 ejecutable", 415),
        (b"%PDF-1.4\n%garbage sin estructura\n", 422),
        (b"", 422),
    ],
)
async def test_solo_pdf_reales(
    editor: AsyncClient, db_session: AsyncSession, contenido: bytes, status: int
) -> None:
    response = await subir(editor, contenido)

    assert response.status_code == status
    assert await db_session.scalar(select(DocumentoVersion)) is None


async def test_pdf_con_javascript_o_cifrado(editor: AsyncClient) -> None:
    con_js = await subir(editor, pdf(js=True))
    cifrado = await subir(editor, pdf(clave="secreta"), titulo="Memoria")

    assert con_js.status_code == 422
    assert "contenido activo" in con_js.json()["detail"]
    assert cifrado.status_code == 422


async def test_pdf_alterado_no_se_sirve(
    editor: AsyncClient, client: AsyncClient, db_session: AsyncSession
) -> None:
    doc = (await subir(editor, pdf(2))).json()
    await editor.post(f"/api/v1/cms/documentos/{doc['id']}/estado", json={"estado": "PUBLICADO"})
    version = await db_session.scalar(select(DocumentoVersion))
    assert version is not None
    ruta = anyio.Path(upload_root(get_settings()) / version.archivo)
    await ruta.write_bytes(pdf(1))

    publico = await client.get("/api/v1/publico/documentos/estados-contables-2025.pdf")
    detalle = (await editor.get(f"/api/v1/cms/documentos/{doc['id']}")).json()

    assert publico.status_code == 503
    assert publico.headers["content-type"] == "application/problem+json"
    assert detalle["versiones"][0]["integra"] is False
    alerta = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "CMS_DOCUMENTO_ALTERADO")
    )
    assert alerta is not None and alerta.severity == "CRITICAL"


async def test_novedades(
    editor: AsyncClient, client: AsyncClient, db_session: AsyncSession
) -> None:
    creada = await editor.post(
        "/api/v1/cms/novedades",
        json={
            "titulo": "Nuevo valor del aporte mínimo",
            "resumen": "Rige desde junio.",
            "contenido": "Primer párrafo.\n\nSegundo párrafo con <script>alert(1)</script>.",
        },
    )
    assert creada.status_code == 201
    n = creada.json()
    assert n["slug"] == "nuevo-valor-del-aporte-minimo"
    url = f"/api/v1/publico/novedades/{n['slug']}"
    assert (await client.get(url)).status_code == 404

    publicar = await editor.post(
        f"/api/v1/cms/novedades/{n['id']}/estado", json={"estado": "PUBLICADO"}
    )
    assert publicar.status_code == 200, publicar.text
    assert publicar.json()["estado"] == "PUBLICADO"
    publica = await client.get(url)
    lista = (await client.get("/api/v1/publico/novedades")).json()
    cambiar_slug = await editor.put(
        f"/api/v1/cms/novedades/{n['id']}",
        json={"titulo": n["titulo"], "contenido": n["contenido"], "slug": "otro-enlace"},
    )

    assert publica.status_code == 200
    # Se guarda como texto: el sitio lo muestra escapado, nunca como HTML.
    assert "<script>" in publica.json()["contenido"]
    assert [i["slug"] for i in lista["items"]] == [n["slug"]]
    assert "contenido" not in lista["items"][0]
    assert cambiar_slug.status_code == 409
    archivar = await editor.post(
        f"/api/v1/cms/novedades/{n['id']}/estado", json={"estado": "ARCHIVADO"}
    )
    assert archivar.status_code == 200
    assert (await client.get(url)).status_code == 404
    assert {"CMS_NOVEDAD_CREADA", "CMS_NOVEDAD_ESTADO"} <= await _eventos(db_session)


async def test_autoridades(editor: AsyncClient, client: AsyncClient) -> None:
    presidente = (
        await editor.post(
            "/api/v1/cms/autoridades",
            json={"cargo": "Presidente", "nombre": "Escribano Sintético", "orden": 1},
        )
    ).json()
    await editor.post(
        "/api/v1/cms/autoridades",
        json={"cargo": "Tesorero", "nombre": "Escribana Sintética", "orden": 2},
    )
    baja = await editor.put(
        f"/api/v1/cms/autoridades/{presidente['id']}",
        json={
            "cargo": "Presidente",
            "nombre": "Escribano Sintético",
            "orden": 1,
            "is_active": False,
        },
    )

    assert baja.status_code == 200 and baja.json()["is_active"] is False
    sitio = (await client.get("/api/v1/publico/sitio")).json()
    assert [a["cargo"] for a in sitio["autoridades"]] == ["Tesorero"]


async def test_permisos(client: AsyncClient, db_session: AsyncSession) -> None:
    escribano = await make_user(db_session)
    await login(client, escribano)

    assert (await client.get("/api/v1/cms/documentos")).status_code == 403
    assert (await subir(client, pdf())).status_code == 403
    assert (await client.get("/api/v1/publico/sitio")).status_code == 200


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE cms_documentos SET estado = 'BORRADOR'",
        "UPDATE cms_documento_versiones SET sha256 = 'x'",
        "DELETE FROM cms_documento_versiones",
        "UPDATE cms_documentos SET slug = 'otro'",
        "DELETE FROM cms_documentos",
        "TRUNCATE cms_autoridades CASCADE",
        "UPDATE cms_documentos SET fecha_publicacion = now() - interval '1 day'",
        "UPDATE cms_documentos SET primera_version_publica = 99",
    ],
)
async def test_inmutable_en_la_base(
    editor: AsyncClient, db_session: AsyncSession, statement: str
) -> None:
    doc = (await subir(editor, pdf())).json()
    await editor.post(f"/api/v1/cms/documentos/{doc['id']}/estado", json={"estado": "PUBLICADO"})
    rechazo = (
        r"permission denied|no permitido|no cambia|no se modifica|no vuelve a borrador"
        r"|publicacion_coherente"
    )

    with pytest.raises(DBAPIError, match=rechazo):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


def _pdf_con(raiz_extra: dict[str, Any]) -> bytes:
    """PDF con entradas agregadas al catálogo (para fabricar casos maliciosos)."""
    from pypdf.generic import NameObject

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    for clave, valor in raiz_extra.items():
        writer._root_object[NameObject(clave)] = valor
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


async def test_contenido_activo_escondido(editor: AsyncClient) -> None:
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject

    # Acción de lanzamiento: el escaneo de bytes no la nombra igual que el grafo.
    lanzar = DictionaryObject(
        {
            NameObject("/S"): NameObject("/Launch"),
            NameObject("/F"): TextStringObject("calc.exe"),
        }
    )
    con_launch = _pdf_con({"/OpenAction": lanzar})
    # Nombre con escape hexadecimal en el catálogo: el escaneo de bytes no lo ve, pero pypdf lo
    # normaliza a /JavaScript al parsear y el recorrido del grafo lo encuentra.
    nombres = DictionaryObject({NameObject("/JavaScript"): DictionaryObject()})
    escondido = _pdf_con({"/Names": nombres}).replace(b"/JavaScript", b"/Java#53cript")
    assert b"/JavaScript" not in escondido

    assert (await subir(editor, con_launch)).status_code == 422
    assert (await subir(editor, escondido, titulo="Memoria")).status_code == 422


async def test_versiones_de_borrador_no_son_publicas(
    editor: AsyncClient, client: AsyncClient
) -> None:
    doc = (await subir(editor, pdf(1))).json()
    await editor.post(
        f"/api/v1/cms/documentos/{doc['id']}/versiones",
        data={"motivo": "Corrección antes de publicar"},
        files={"archivo": ("v2.pdf", pdf(2), "application/pdf")},
    )
    await editor.post(f"/api/v1/cms/documentos/{doc['id']}/estado", json={"estado": "PUBLICADO"})

    sitio = (await client.get("/api/v1/publico/sitio")).json()
    borrador = await client.get("/api/v1/publico/documentos/estados-contables-2025/v1.pdf")
    vigente = await client.get("/api/v1/publico/documentos/estados-contables-2025/v2.pdf")

    assert sitio["documentos"][0]["version"] == 2
    assert sitio["documentos"][0]["versiones_anteriores"] == []
    assert borrador.status_code == 404
    assert vigente.status_code == 200
