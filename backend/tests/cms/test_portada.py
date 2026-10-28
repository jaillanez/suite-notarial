"""Sitio como diario: secciones, imagen de las notas, páginas del menú y armado de portada."""

import io
import json
from typing import Any

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.core.config import get_settings
from app.modules.cms.models import Novedad
from app.modules.pagos.storage import upload_root
from tests.cms.test_cms import editor, pdf
from tests.iam.factories import make_user
from tests.iam.test_rbac import login

__all__ = ["editor"]


def png(color: str = "#113347") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 18), color).save(buffer, "PNG")
    return buffer.getvalue()


async def nota(
    editor: AsyncClient, titulo: str, *, seccion: str = "NOVEDADES", publicar: bool = True
) -> Any:
    creada = await editor.post(
        "/api/v1/cms/novedades",
        json={"titulo": titulo, "seccion": seccion, "contenido": "Texto de la nota de prueba."},
    )
    assert creada.status_code == 201, creada.text
    n = creada.json()
    if publicar:
        r = await editor.post(
            f"/api/v1/cms/novedades/{n['id']}/estado", json={"estado": "PUBLICADO"}
        )
        assert r.status_code == 200
    return n


async def _eventos(db_session: AsyncSession) -> list[str]:
    return list((await db_session.scalars(select(AuditSecurityLog.event_type))).all())


async def test_seccion_de_la_nota_y_filtro_publico(
    editor: AsyncClient, client: AsyncClient
) -> None:
    await nota(editor, "Aporte médico de septiembre", seccion="APORTES")
    await nota(editor, "Nuevas autoridades", seccion="INSTITUCIONAL")

    aportes = (await client.get("/api/v1/publico/novedades?seccion=APORTES")).json()
    assert [i["titulo"] for i in aportes["items"]] == ["Aporte médico de septiembre"]
    assert aportes["items"][0]["seccion_texto"] == "Aportes"
    assert (await client.get("/api/v1/publico/novedades?seccion=OTRA")).status_code == 422


async def test_imagen_de_la_nota(
    editor: AsyncClient, client: AsyncClient, db_session: AsyncSession
) -> None:
    n = await nota(editor, "Nota con foto", publicar=False)
    subida = await editor.post(
        f"/api/v1/cms/novedades/{n['id']}/imagen",
        data={"alt": "Firma de una escritura"},
        files={"archivo": ("foto.png", png(), "image/png")},
    )
    assert subida.status_code == 200, subida.text
    assert subida.json()["imagen_alt"] == "Firma de una escritura"
    # En borrador, la ve el editor pero no el público.
    admin = await editor.get(subida.json()["imagen_url"])
    assert admin.status_code == 200 and admin.headers["content-type"] == "image/png"
    assert (await client.get(f"/api/v1/publico/novedades/{n['slug']}/imagen")).status_code == 404

    await editor.post(f"/api/v1/cms/novedades/{n['id']}/estado", json={"estado": "PUBLICADO"})
    publica = (await client.get(f"/api/v1/publico/novedades/{n['slug']}")).json()
    imagen = await client.get(publica["imagen_url"])
    assert imagen.status_code == 200
    assert imagen.content == png()
    assert "immutable" in imagen.headers["cache-control"]
    assert imagen.headers["x-content-type-options"] == "nosniff"

    quitada = await editor.post(f"/api/v1/cms/novedades/{n['id']}/imagen/quitar")
    assert quitada.json()["imagen_url"] is None
    assert (await _eventos(db_session)).count("CMS_NOVEDAD_IMAGEN") == 2


async def test_imagen_alterada_no_se_sirve(
    editor: AsyncClient, client: AsyncClient, db_session: AsyncSession
) -> None:
    n = await nota(editor, "Nota alterada")
    await editor.post(
        f"/api/v1/cms/novedades/{n['id']}/imagen",
        data={"alt": "Imagen"},
        files={"archivo": ("foto.png", png(), "image/png")},
    )
    guardada = await db_session.get(Novedad, n["id"])
    assert guardada is not None and guardada.imagen_ruta is not None
    (upload_root(get_settings()) / guardada.imagen_ruta).write_bytes(png("#ff0000"))

    assert (await client.get(f"/api/v1/publico/novedades/{n['slug']}/imagen")).status_code == 404


@pytest.mark.parametrize(
    ("nombre", "contenido", "status"),
    [
        ("foto.png", pdf(), 415),  # un PDF con extensión de imagen
        ("foto.jpg", b"<svg onload='alert(1)'/>", 415),
        ("foto.png", b"", 422),
    ],
)
async def test_solo_imagenes_reales(
    editor: AsyncClient, nombre: str, contenido: bytes, status: int
) -> None:
    n = await nota(editor, f"Nota {nombre} {status}", publicar=False)
    r = await editor.post(
        f"/api/v1/cms/novedades/{n['id']}/imagen",
        data={"alt": "Imagen"},
        files={"archivo": (nombre, contenido, "image/png")},
    )
    assert r.status_code == status


async def test_paginas_del_menu(
    editor: AsyncClient, client: AsyncClient, db_session: AsyncSession
) -> None:
    creada = await editor.post(
        "/api/v1/cms/paginas",
        json={
            "grupo": "CAJA",
            "titulo": "Quiénes somos",
            "contenido": "La Caja Notarial de San Juan fue creada por la Ley 6.043.",
        },
    )
    assert creada.status_code == 201, creada.text
    p = creada.json()
    assert p["slug"] == "quienes-somos"
    url = f"/api/v1/publico/paginas/{p['slug']}"
    assert (await client.get(url)).status_code == 404
    assert (await client.get("/api/v1/publico/sitio")).json()["menu"] == []

    await editor.post(f"/api/v1/cms/paginas/{p['id']}/estado", json={"estado": "PUBLICADO"})
    publica = (await client.get(url)).json()
    assert publica["grupo_texto"] == "Caja"
    menu = (await client.get("/api/v1/publico/sitio")).json()["menu"]
    assert menu == [{"slug": "quienes-somos", "grupo": "CAJA", "titulo": "Quiénes somos"}]

    otro_enlace = await editor.put(
        f"/api/v1/cms/paginas/{p['id']}",
        json={"grupo": "CAJA", "titulo": "Quiénes somos", "contenido": p["contenido"], "slug": "x"},
    )
    assert otro_enlace.status_code == 409
    assert {"CMS_PAGINA_CREADA", "CMS_PAGINA_ESTADO"} <= set(await _eventos(db_session))


async def test_portada_armada(
    editor: AsyncClient, client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await nota(editor, "Principal")
    b = await nota(editor, "Segunda")
    c = await nota(editor, "Tercera")
    borrador = await nota(editor, "Borrador", publicar=False)

    guardada = await editor.put(
        "/api/v1/cms/portada",
        json={
            "destacadas": [a["id"], borrador["id"]],
            "filas": [
                {"distribucion": "2+1+1", "notas": [b["id"], None, c["id"]]},
                {"distribucion": "4", "notas": [borrador["id"]]},
            ],
        },
    )
    assert guardada.status_code == 200, guardada.text
    assert guardada.json()["actualizada_por"] is not None

    portada = (await client.get("/api/v1/publico/sitio")).json()["portada"]
    # Solo lo publicado: el borrador no aparece y su fila entera se omite.
    assert [n["titulo"] for n in portada["destacadas"]] == ["Principal"]
    assert [(f["distribucion"], [n["titulo"] for n in f["notas"]]) for f in portada["filas"]] == [
        ("2+1+1", ["Segunda", "Tercera"])
    ]
    # Archivar una nota la saca de la portada sin rearmarla.
    await editor.post(f"/api/v1/cms/novedades/{a['id']}/estado", json={"estado": "ARCHIVADO"})
    assert (await client.get("/api/v1/publico/sitio")).json()["portada"]["destacadas"] == []
    # El editor recupera el armado tal como lo guardó.
    actual = (await editor.get("/api/v1/cms/portada")).json()
    assert actual["destacadas"] == [a["id"], borrador["id"]]
    assert actual["filas"][0]["notas"] == [b["id"], None, c["id"]]
    assert "CMS_PORTADA_ACTUALIZADA" in await _eventos(db_session)


async def test_portada_sin_armar_usa_las_ultimas(editor: AsyncClient, client: AsyncClient) -> None:
    for i in range(5):
        await nota(editor, f"Nota automática {i}")
    portada = (await client.get("/api/v1/publico/sitio")).json()["portada"]
    assert [n["titulo"] for n in portada["destacadas"]] == ["Nota automática 4"]
    assert [len(f["notas"]) for f in portada["filas"]] == [3, 1]


@pytest.mark.parametrize(
    ("cuerpo", "detalle"),
    [
        ({"filas": [{"distribucion": "2+2", "notas": [None]}]}, "2 espacios"),
        ({"destacadas": ["{a}", "{a}"]}, "dos veces"),
        ({"filas": [{"distribucion": "2+2", "notas": ["{a}", "{a}"]}]}, "dos veces"),
        ({"destacadas": ["00000000-0000-4000-8000-000000000000"]}, "no existen"),
        ({"filas": [{"distribucion": "5", "notas": []}]}, None),
    ],
)
async def test_portada_invalida(
    editor: AsyncClient, cuerpo: dict[str, Any], detalle: str | None
) -> None:
    a = await nota(editor, "Nota a")
    texto = json.dumps(cuerpo).replace("{a}", a["id"])
    r = await editor.put("/api/v1/cms/portada", json=json.loads(texto))
    assert r.status_code == 422
    if detalle:
        assert detalle in r.json()["detail"]


async def test_permisos_del_gestor(client: AsyncClient, db_session: AsyncSession) -> None:
    escribano = await make_user(db_session)
    await login(client, escribano)

    assert (await client.get("/api/v1/cms/portada")).status_code == 403
    assert (await client.put("/api/v1/cms/portada", json={})).status_code == 403
    assert (await client.get("/api/v1/cms/paginas")).status_code == 403


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE cms_portada_versiones SET configuracion = '{}'",
        "DELETE FROM cms_portada_versiones",
        "DELETE FROM cms_paginas",
        "UPDATE cms_paginas SET estado = 'BORRADOR'",
        "UPDATE cms_paginas SET slug = 'otro'",
    ],
)
async def test_inmutable_en_la_base(
    editor: AsyncClient, db_session: AsyncSession, statement: str
) -> None:
    p = (
        await editor.post(
            "/api/v1/cms/paginas",
            json={"grupo": "NORMATIVA", "titulo": "Ley 7.231", "contenido": "Texto de la ley."},
        )
    ).json()
    await editor.post(f"/api/v1/cms/paginas/{p['id']}/estado", json={"estado": "PUBLICADO"})
    await editor.put("/api/v1/cms/portada", json={"destacadas": [], "filas": []})

    with pytest.raises(
        DBAPIError, match=r"permission denied|no permitido|no cambia|no se modifica|no vuelve"
    ):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))
