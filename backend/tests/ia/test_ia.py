"""IA asistencial de punta a punta: la IA sugiere, la persona revisa y corrige, y recién al
ratificar se crea el acto o el escribano, con las validaciones de la carga manual (regla HIC)."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.ddjj.models import Acto, Boleta, DeclaracionJurada
from app.modules.ia import lectura
from app.modules.padron.models import Escribano, Persona
from tests.ddjj.conftest import Escenario
from tests.ia.conftest import DNI_NUEVO, imagen_texto, minuta, pdf417_png


async def _analizar(client: AsyncClient, ddjj: dict[str, Any], texto: str) -> dict[str, Any]:
    response = await client.post("/api/v1/ia/minutas", data={"ddjj_id": ddjj["id"], "texto": texto})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _confirmado(sugerencia: dict[str, Any], **cambios: Any) -> dict[str, Any]:
    """Lo que la persona confirma: los valores sugeridos, con sus correcciones."""
    campos = {k: v["valor"] for k, v in sugerencia["campos"].items()}
    cuerpo = {
        "escribano_id": campos["escribano_id"],
        "tipo_protocolo": campos["tipo_protocolo"],
        "numero_escritura": int(campos["numero_escritura"]),
        "folio": int(campos["folio"]) if campos["folio"] else None,
        "fecha_acto": campos["fecha_acto"],
        "naturaleza": campos["naturaleza"],
        "categoria": campos["categoria"],
        "base_imponible": campos["base_imponible"],
    }
    return {**cuerpo, **cambios}


async def _contar(session: AsyncSession, modelo: Any, *where: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(modelo).where(*where)) or 0)


async def test_minuta_sugiere_sin_escribir_nada(
    notario: AsyncClient,
    escenario: Escenario,
    borrador: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    s = await _analizar(notario, borrador, minuta(escenario))
    assert s["estado"] == "SUGERIDO_POR_IA"
    assert s["tipo"] == "EXTRACCION_MINUTA"
    assert s["motor"] == "reglas-minuta"
    valores = {k: v["valor"] for k, v in s["campos"].items()}
    assert valores["escribano_id"] == str(escenario.titular.id)
    assert valores["numero_escritura"] == "120"
    assert valores["fecha_acto"] == "2026-09-14"
    assert valores["base_imponible"] == "45000000.00"
    assert all(v["regla"] for v in s["campos"].values())
    # Del texto quedan el largo y el hash, no el contenido.
    assert s["entrada"]["origen"] == "texto"
    assert s["entrada"]["caracteres"] == len(minuta(escenario))

    # HIC: analizar no crea actos, no presenta, no emite boletas.
    assert await _contar(db_session, Acto, Acto.ddjj_id == borrador["id"]) == 0
    assert await _contar(db_session, Boleta, Boleta.ddjj_id == borrador["id"]) == 0
    estado = await db_session.scalar(
        select(DeclaracionJurada.estado).where(DeclaracionJurada.id == borrador["id"])
    )
    assert estado == "BORRADOR"

    log = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "IA_SUGERENCIA_GENERADA")
    )
    assert log is not None and log.details is not None
    assert log.details["sugerencia_id"] == s["id"]
    # Sin datos del documento en la auditoría.
    assert "Sintético" not in str(log.details) and "45000000" not in str(log.details)


async def test_ratificar_con_correccion_crea_el_acto(
    notario: AsyncClient,
    escenario: Escenario,
    borrador: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    s = await _analizar(notario, borrador, minuta(escenario))
    ratificado = await notario.post(
        f"/api/v1/ia/sugerencias/{s['id']}/ratificar-acto", json=_confirmado(s, folio=346)
    )
    assert ratificado.status_code == 200, ratificado.text
    body = ratificado.json()
    assert body["sugerencia"]["estado"] == "RATIFICADA"
    assert body["sugerencia"]["campos_modificados"] == ["folio"]
    assert body["acto"]["folio"] == 346
    assert body["acto"]["base_imponible"] == "45000000.00"
    assert body["sugerencia"]["acto_id"] == body["acto"]["id"]

    # El acto entra por el camino normal: aparece en la DDJJ, con su aporte calculado en el
    # servidor (la IA no propone aportes).
    detalle = (await notario.get(f"/api/v1/ddjj/declaraciones/{borrador['id']}")).json()
    assert [a["id"] for a in detalle["actos"]] == [body["acto"]["id"]]
    assert "aporte" not in s["campos"]

    eventos = (
        await db_session.scalars(
            select(AuditSecurityLog.event_type).where(
                AuditSecurityLog.event_type.in_(["IA_SUGERENCIA_RATIFICADA", "DDJJ_ACTO_AGREGADO"])
            )
        )
    ).all()
    assert sorted(eventos) == ["DDJJ_ACTO_AGREGADO", "IA_SUGERENCIA_RATIFICADA"]
    log = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "IA_SUGERENCIA_RATIFICADA")
    )
    assert log is not None and log.details is not None
    assert log.details["fue_modificada"] is True
    assert log.details["campos_modificados"] == ["folio"]

    # Una sugerencia se ratifica una sola vez.
    otra_vez = await notario.post(
        f"/api/v1/ia/sugerencias/{s['id']}/ratificar-acto", json=_confirmado(s, folio=347)
    )
    assert otra_vez.status_code == 409


async def test_ratificar_valida_como_la_carga_manual(
    notario: AsyncClient,
    escenario: Escenario,
    borrador: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    s = await _analizar(notario, borrador, minuta(escenario))
    fuera = await notario.post(
        f"/api/v1/ia/sugerencias/{s['id']}/ratificar-acto",
        json=_confirmado(s, fecha_acto="2026-08-31"),
    )
    assert fuera.status_code == 422
    assert "período" in fuera.json()["detail"]
    # Nada quedó a medias: la sugerencia sigue pendiente y no hay acto.
    sigue = (await notario.get(f"/api/v1/ia/sugerencias/{s['id']}")).json()
    assert sigue["estado"] == "SUGERIDO_POR_IA"
    assert await _contar(db_session, Acto, Acto.ddjj_id == borrador["id"]) == 0

    # Número ya declarado (409 de la carga manual): tampoco queda ratificada.
    manual = await notario.post(
        f"/api/v1/ddjj/declaraciones/{borrador['id']}/actos", json=_confirmado(s)
    )
    assert manual.status_code == 201, manual.text
    s2 = await _analizar(notario, borrador, minuta(escenario))
    assert "NUMERO_YA_DECLARADO" in {a["codigo"] for a in s2["alertas"]}
    repetido = await notario.post(
        f"/api/v1/ia/sugerencias/{s2['id']}/ratificar-acto", json=_confirmado(s2)
    )
    assert repetido.status_code == 409
    assert (await notario.get(f"/api/v1/ia/sugerencias/{s2['id']}")).json()[
        "estado"
    ] == "SUGERIDO_POR_IA"


async def test_solo_quien_pidio_ve_y_ratifica(
    notario: AsyncClient,
    staff: AsyncClient,
    escenario: Escenario,
    borrador: dict[str, Any],
) -> None:
    s = await _analizar(notario, borrador, minuta(escenario))
    assert (await staff.get(f"/api/v1/ia/sugerencias/{s['id']}")).status_code == 404
    ajeno = await staff.post(
        f"/api/v1/ia/sugerencias/{s['id']}/ratificar-acto", json=_confirmado(s)
    )
    assert ajeno.status_code == 404
    assert (
        await staff.post(f"/api/v1/ia/sugerencias/{s['id']}/descartar", json={})
    ).status_code == 404


async def test_permisos_y_alcance(
    client: AsyncClient,
    notario: AsyncClient,
    escenario: Escenario,
    borrador: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    from tests.iam.factories import make_user
    from tests.iam.test_rbac import login

    sin_permiso = await make_user(db_session, roles=("ROLE_AUDITOR",))
    await login(client, sin_permiso)
    assert (
        await client.post(
            "/api/v1/ia/minutas", data={"ddjj_id": borrador["id"], "texto": minuta(escenario)}
        )
    ).status_code == 403
    assert (
        await client.post("/api/v1/ia/dni", files={"archivo": ("dni.png", b"x", "image/png")})
    ).status_code == 403
    # El escribano no da de alta escribanos: no lee DNI.
    assert (
        await notario.post(
            "/api/v1/ia/dni",
            files={"archivo": ("dni.png", pdf417_png(DNI_NUEVO), "image/png")},
        )
    ).status_code == 403

    # DDJJ de otro registro: no se revela.
    otro = await notario.post(
        "/api/v1/ia/minutas",
        data={"ddjj_id": "00000000-0000-4000-8000-000000000000", "texto": minuta(escenario)},
    )
    assert otro.status_code == 404
    # Ni archivo ni texto (o los dos): 422.
    vacio = await notario.post("/api/v1/ia/minutas", data={"ddjj_id": borrador["id"]})
    assert vacio.status_code == 422


async def test_descartar(
    notario: AsyncClient, escenario: Escenario, borrador: dict[str, Any]
) -> None:
    s = await _analizar(notario, borrador, minuta(escenario))
    descartada = await notario.post(
        f"/api/v1/ia/sugerencias/{s['id']}/descartar", json={"motivo": "Minuta equivocada"}
    )
    assert descartada.status_code == 200
    assert descartada.json()["estado"] == "DESCARTADA"
    tarde = await notario.post(
        f"/api/v1/ia/sugerencias/{s['id']}/ratificar-acto", json=_confirmado(s)
    )
    assert tarde.status_code == 409


async def test_archivo_falsificado_y_pdf_con_texto(
    notario: AsyncClient, escenario: Escenario, borrador: dict[str, Any]
) -> None:
    falso = await notario.post(
        "/api/v1/ia/minutas",
        data={"ddjj_id": borrador["id"]},
        files={"archivo": ("minuta.png", b"esto no es una imagen", "image/png")},
    )
    assert falso.status_code == 415

    from weasyprint import HTML

    pdf = HTML(string=f"<p>{minuta(escenario)}</p>").write_pdf()
    assert pdf is not None
    leido = await notario.post(
        "/api/v1/ia/minutas",
        data={"ddjj_id": borrador["id"]},
        files={"archivo": ("minuta.pdf", pdf, "application/pdf")},
    )
    assert leido.status_code == 201, leido.text
    body = leido.json()
    assert body["entrada"]["mime_type"] == "application/pdf"
    assert body["campos"]["numero_escritura"]["valor"] == "120"


@pytest.mark.skipif(not lectura.estado_ocr()[0], reason="Tesseract no está instalado")
async def test_minuta_escaneada_por_ocr(
    notario: AsyncClient, escenario: Escenario, borrador: dict[str, Any]
) -> None:
    response = await notario.post(
        "/api/v1/ia/minutas",
        data={"ddjj_id": borrador["id"]},
        files={"archivo": ("minuta.png", imagen_texto(minuta(escenario)), "image/png")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["entrada"]["ocr"]
    assert body["campos"]["numero_escritura"]["valor"] == "120"
    assert body["campos"]["base_imponible"]["valor"] == "45000000.00"


async def test_dni_sugiere_y_el_alta_se_ratifica(
    staff: AsyncClient, db_session: AsyncSession
) -> None:
    leido = await staff.post(
        "/api/v1/ia/dni", files={"archivo": ("dni.png", pdf417_png(DNI_NUEVO), "image/png")}
    )
    assert leido.status_code == 201, leido.text
    s = leido.json()
    assert s["motor"] == "dni-pdf417"
    campos = {k: v["valor"] for k, v in s["campos"].items()}
    assert campos == {
        "numero_documento": "12345678",
        "apellido": "Sintetico de la Prueba",
        "nombre": "Juan Carlos",
        "fecha_nacimiento": "1975-03-15",
        "cuit": "20123456786",
    }
    # Nada en el padrón todavía.
    assert await _contar(db_session, Persona, Persona.numero_documento == "12345678") == 0

    # La persona corrige el apellido (tilde) y completa la matrícula.
    cuerpo = {
        "persona": {
            "cuit": campos["cuit"],
            "numero_documento": campos["numero_documento"],
            "apellido": "Sintético de la Prueba",
            "nombre": campos["nombre"],
            "fecha_nacimiento": campos["fecha_nacimiento"],
        },
        "matricula_numero": 98_765,
        "fecha_matriculacion": "2026-10-01",
    }
    ratificado = await staff.post(
        f"/api/v1/ia/sugerencias/{s['id']}/ratificar-escribano", json=cuerpo
    )
    assert ratificado.status_code == 200, ratificado.text
    body = ratificado.json()
    assert body["sugerencia"]["campos_modificados"] == ["apellido"]
    assert body["escribano"]["persona"]["apellido"] == "Sintético de la Prueba"
    escribano = await db_session.get(Escribano, body["escribano"]["id"])
    assert escribano is not None and escribano.matricula_numero == 98_765

    # Un segundo DNI igual avisa que ya está en el padrón.
    otra = await staff.post(
        "/api/v1/ia/dni", files={"archivo": ("dni.png", pdf417_png(DNI_NUEVO), "image/png")}
    )
    assert "DNI_EN_PADRON" in {a["codigo"] for a in otra.json()["alertas"]}


async def test_dni_ilegible(staff: AsyncClient) -> None:
    ilegible = await staff.post(
        "/api/v1/ia/dni",
        files={"archivo": ("dni.png", imagen_texto("una foto sin código"), "image/png")},
    )
    assert ilegible.status_code == 422
    assert "No se pudo leer el DNI" in ilegible.json()["detail"]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ia_sugerencias SET salida = '{}'::jsonb",
        "UPDATE ia_sugerencias SET confianza = 1",
        "UPDATE ia_sugerencias SET estado = 'DESCARTADA', resuelto_en = now(), "
        "resuelto_por_user_id = solicitado_por_user_id, motivo_descarte = 'x', "
        "motor = 'otro'",
        "DELETE FROM ia_sugerencias",
        "TRUNCATE ia_sugerencias",
    ],
)
async def test_inmutable_en_la_base(
    notario: AsyncClient,
    escenario: Escenario,
    borrador: dict[str, Any],
    db_session: AsyncSession,
    statement: str,
) -> None:
    await _analizar(notario, borrador, minuta(escenario))
    with pytest.raises(
        DBAPIError, match=r"no se modifica|no se borran|solo cambia|permission denied"
    ):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_resuelta_queda_congelada(
    notario: AsyncClient,
    escenario: Escenario,
    borrador: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    s = await _analizar(notario, borrador, minuta(escenario))
    await notario.post(f"/api/v1/ia/sugerencias/{s['id']}/descartar", json={})
    with pytest.raises(DBAPIError, match="resuelta no se modifica"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE ia_sugerencias SET motivo_descarte = 'otro' WHERE id = :id"),
                {"id": s["id"]},
            )


async def test_reporte_de_sugerencias(
    notario: AsyncClient,
    auditor: AsyncClient,
    escenario: Escenario,
    borrador: dict[str, Any],
) -> None:
    corregida = await _analizar(notario, borrador, minuta(escenario))
    await notario.post(
        f"/api/v1/ia/sugerencias/{corregida['id']}/ratificar-acto",
        json=_confirmado(corregida, folio=400, naturaleza="Compraventa de inmueble"),
    )
    pendiente = await _analizar(notario, borrador, minuta(escenario, numero="DOSCIENTOS (200)"))

    pantalla = await auditor.get("/api/v1/reportes/SUGERENCIAS_IA", params={"page_size": 50})
    assert pantalla.status_code == 200, pantalla.text
    filas = {f["id"]: f for f in pantalla.json()["items"]}
    assert filas[corregida["id"]]["estado"] == "Ratificada"
    assert filas[corregida["id"]]["corregida"] == "Sí"
    assert filas[corregida["id"]]["campos_corregidos"] == "folio, naturaleza"
    assert filas[pendiente["id"]]["estado"] == "Sugerido por IA (sin ratificar)"
    assert filas[pendiente["id"]]["corregida"] is None

    # Misma consulta para pantalla y export (regla REP).
    csv = await auditor.get("/api/v1/reportes/SUGERENCIAS_IA/export", params={"formato": "csv"})
    assert csv.status_code == 200, csv.text
    assert csv.text.count("\r\n") == pantalla.json()["total"] + 2  # encabezado y totales
    # El notario no ve el reporte de auditoría.
    assert (await notario.get("/api/v1/reportes/SUGERENCIAS_IA")).status_code == 403


async def test_registro_minimizado(
    notario: AsyncClient,
    escenario: Escenario,
    borrador: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    """La respuesta trae valores y citas; la fila (que no se borra) solo huellas y códigos."""
    from app.modules.ia.models import Sugerencia

    s = await _analizar(notario, borrador, minuta(escenario))
    assert s["campos"]["base_imponible"]["evidencia"]
    await notario.post(
        f"/api/v1/ia/sugerencias/{s['id']}/ratificar-acto", json=_confirmado(s, folio=346)
    )
    fila = await db_session.get(Sugerencia, s["id"])
    assert fila is not None
    await db_session.refresh(fila)
    guardado = str(fila.salida) + str(fila.datos_confirmados) + str(fila.entrada)
    for dato in ("45000000", "Sintético", "20-12345678-6", "Juan Carlos", "'valor'"):
        assert dato not in guardado, dato
    assert "'evidencia'" not in guardado and "'mensaje'" not in guardado
    assert fila.campos_modificados == ["folio"]
    # Releer la sugerencia ya no devuelve los valores (no están guardados).
    leida = (await notario.get(f"/api/v1/ia/sugerencias/{s['id']}")).json()
    assert leida["campos"]["numero_escritura"]["valor"] is None
    assert leida["campos"]["numero_escritura"]["regla"]


async def test_pdf_con_demasiado_texto(notario: AsyncClient, borrador: dict[str, Any]) -> None:
    from weasyprint import HTML

    parrafo = "Texto de relleno sin datos. " * 400
    # Hoja grande y letra chica: pocas páginas con cualquier fuente (el tope que se prueba es el
    # de caracteres, no el de páginas).
    estilo = "<style>@page{size:A3;margin:5mm} p{font-size:4pt;line-height:1}</style>"
    pdf = HTML(string=estilo + "".join(f"<p>{parrafo}</p>" for _ in range(20))).write_pdf()
    assert pdf is not None
    response = await notario.post(
        "/api/v1/ia/minutas",
        data={"ddjj_id": borrador["id"]},
        files={"archivo": ("largo.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 413
    assert "demasiado texto" in response.json()["detail"]


async def test_cola_llena(
    notario: AsyncClient,
    escenario: Escenario,
    borrador: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def llena() -> None:
        raise lectura.ColaLlenaError

    monkeypatch.setattr(lectura, "_con_lugar", llena)
    response = await notario.post(
        "/api/v1/ia/minutas", data={"ddjj_id": borrador["id"], "texto": minuta(escenario)}
    )
    assert response.status_code == 503
    assert "lecturas en curso" in response.json()["detail"]


def _pdf_con_flujo(
    datos: bytes, filtro: str = "/FlateDecode", extra: list[bytes] | None = None
) -> bytes:
    """PDF mínimo de una página cuyo contenido es `datos` ya codificado."""
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        f"<< /Length {len(datos)} /Filter {filtro} >>\nstream\n".encode() + datos + b"\nendstream",
        *(extra or []),
    ]
    salida = bytearray(b"%PDF-1.7\n")
    posiciones = []
    for n, cuerpo in enumerate(objetos, start=1):
        posiciones.append(len(salida))
        salida += f"{n} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += b"".join(f"{p:010d} 00000 n \n".encode() for p in posiciones)
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n".encode()
    salida += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(salida)


async def test_pdf_bomba_de_descompresion(notario: AsyncClient, borrador: dict[str, Any]) -> None:
    import zlib

    # ~30 KB comprimidos que se inflan a 30 MB: se rechaza sin inflarlo entero.
    bomba = _pdf_con_flujo(zlib.compress(b" " * 30_000_000, 9))
    assert len(bomba) < 100_000
    response = await notario.post(
        "/api/v1/ia/minutas",
        data={"ddjj_id": borrador["id"]},
        files={"archivo": ("bomba.pdf", bomba, "application/pdf")},
    )
    assert response.status_code == 413
    assert "demasiado pesado" in response.json()["detail"]

    # La bomba fuera del contenido de la página (p. ej. una fuente) también cuenta.
    escondida = zlib.compress(b"\x00" * 30_000_000, 9)
    oculta = _pdf_con_flujo(
        zlib.compress(b"BT ET"),
        extra=[
            f"<< /Length {len(escondida)} /Filter /FlateDecode >>\nstream\n".encode()
            + escondida
            + b"\nendstream"
        ],
    )
    response = await notario.post(
        "/api/v1/ia/minutas",
        data={"ddjj_id": borrador["id"]},
        files={"archivo": ("fuente.pdf", oculta, "application/pdf")},
    )
    assert response.status_code == 413

    otra_compresion = _pdf_con_flujo(b"no importa", "/LZWDecode")
    response = await notario.post(
        "/api/v1/ia/minutas",
        data={"ddjj_id": borrador["id"]},
        files={"archivo": ("lzw.pdf", otra_compresion, "application/pdf")},
    )
    assert response.status_code == 422
    assert "compresión" in response.json()["detail"]


def test_inflado_falla_cerrado() -> None:
    """Sin /Length directo y sin poder medir hasta el final: se cobra el máximo por stream."""
    import zlib

    from app.modules.ia.lectura import MAX_INFLADO_PDF, _controlar_inflado
    from app.modules.pagos.storage import ArchivoInvalidoError

    # Un "endstream" falso dentro de los datos comprimidos corta la medición: no alcanza para
    # esconder el stream, porque cuenta como el tope de pypdf (4 MB). Cinco superan los 16 MB.
    comprimido = zlib.compress(b"A" * 1000)
    trampa = comprimido[:10] + b"endstream" + comprimido[10:]
    stream = (
        b"5 0 obj\n<< /Length 9 0 R /Filter /FlateDecode >>\nstream\n" + trampa + b"\nendstream\n"
    )
    _controlar_inflado(b"%PDF-1.7\n" + stream * 4)
    with pytest.raises(ArchivoInvalidoError, match="demasiado pesado"):
        _controlar_inflado(b"%PDF-1.7\n" + stream * 5)
    # "stream" seguido de espacios y CR también se reconoce, como en pypdf.
    bomba = zlib.compress(b" " * (MAX_INFLADO_PDF + 10))
    raro = b"<< /Length %d /Filter /FlateDecode >>stream \r" % len(bomba) + bomba + b"endstream"
    with pytest.raises(ArchivoInvalidoError, match="demasiado pesado"):
        _controlar_inflado(b"%PDF-1.7\n" + raro)
    # Cadenas de filtros: se rechazan.
    cadena = b"<< /Length 3 /Filter [/ASCIIHexDecode /FlateDecode] >>\nstream\nabc\nendstream"
    with pytest.raises(ArchivoInvalidoError, match="compresión"):
        _controlar_inflado(b"%PDF-1.7\n" + cadena)
