"""Índice del protocolo por foto: cada renglón es una sugerencia de acto; nada entra a la DDJJ
sin ratificación. La visión externa se simula (ningún test llama a DeepSeek)."""

# ruff: noqa: F811

import io
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.core.config import get_settings
from app.modules.ddjj.models import Acto
from app.modules.ia import indice, lectura, vision
from app.modules.ia.minutas import ContextoMinuta
from app.modules.pagos.storage import ArchivoValidado
from tests.ddjj.conftest import Escenario
from tests.ia.conftest import borrador  # noqa: F401 - fixture compartida

RESPUESTA_VISION = """```json
[
  {"numero": "120", "fecha": "14/09/2026", "naturaleza": "Compra-venta",
   "partes": "Pérez Juan a Gómez Ana", "folio": "345", "monto": "$ 45.000.000,00",
   "protocolo": null},
  {"numero": "121", "fecha": "15/09/2026", "naturaleza": "Poder general",
   "partes": "Ruiz Marta a Ruiz Pedro", "folio": 348, "monto": null, "protocolo": null},
  {"numero": "122", "fecha": "02/08/2026", "naturaleza": "Hipoteca",
   "partes": "Gómez Ana a Banco Sintético", "folio": "350", "monto": 9000000.5,
   "protocolo": "Auxiliar"}
]
```"""

CTX = ContextoMinuta(
    periodo_desde=date(2026, 9, 1),
    periodo_hasta=date(2026, 9, 30),
    hoy=date(2026, 10, 23),
    registro_numero=1,
    candidatos=(),
    declarados=frozenset({("GENERAL", 121)}),
)


def _png() -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(salida, "PNG")
    return salida.getvalue()


def _fotos(cantidad: int = 1) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("archivos", (f"indice{i}.png", _png(), "image/png")) for i in range(cantidad)]


@pytest.fixture
def con_vision(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """DeepSeek configurado y simulado: guarda lo que se le habría enviado."""
    settings = get_settings()
    monkeypatch.setattr(settings, "IA_VISION_PROVEEDOR", "deepseek")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", SecretStr("clave-de-prueba"))
    enviados: list[bytes] = []

    async def transcribir(jpeg: bytes) -> vision.LecturaVision:
        enviados.append(jpeg)
        return vision.LecturaVision(RESPUESTA_VISION, "deepseek-v4-flash-vision-exp", 1400)

    monkeypatch.setattr(vision, "transcribir", transcribir)
    return enviados


def _cuerpo(s: dict[str, Any], escribano_id: uuid.UUID, **cambios: Any) -> dict[str, Any]:
    campos = {k: v["valor"] for k, v in s["campos"].items()}
    return {
        "escribano_id": str(escribano_id),
        "tipo_protocolo": campos["tipo_protocolo"],
        "numero_escritura": int(campos["numero_escritura"]),
        "folio": int(campos["folio"]) if campos["folio"] else None,
        "fecha_acto": campos["fecha_acto"],
        "naturaleza": campos["naturaleza"],
        "categoria": campos["categoria"],
        "base_imponible": campos["base_imponible"],
        **cambios,
    }


# --------------------------------------------------------------------------- reglas (sin red)


def test_renglones_de_vision_sin_flotantes() -> None:
    renglones = indice.renglones_de_vision(RESPUESTA_VISION, 1)
    assert [r.numero for r in renglones] == ["120", "121", "122"]
    # Un número que el modelo devuelve suelto se lee como Decimal, nunca como float.
    assert renglones[2].monto == "9000000.5"
    assert renglones[1].folio == "348"
    with pytest.raises(indice.RespuestaInvalidaError):
        indice.renglones_de_vision("No pude leer la imagen.", 1)


def test_renglon_a_acto_con_las_reglas_de_la_minuta() -> None:
    compraventa, poder, hipoteca = (
        indice.a_resultado(r, CTX, confianza=Decimal("0.85"))
        for r in indice.renglones_de_vision(RESPUESTA_VISION, 1)
    )
    c = {k: v.valor for k, v in compraventa.campos.items()}
    assert c["naturaleza"] == "Compraventa"
    assert c["categoria"] == "ESCRITURA_CON_VALOR"
    assert c["base_imponible"] == "45000000.00"
    assert c["fecha_acto"] == "2026-09-14"
    assert c["tipo_protocolo"] == "GENERAL"
    assert compraventa.alertas == []
    # Las partes ayudan a revisar, pero no se guardan.
    assert "Pérez" in (compraventa.campos["naturaleza"].evidencia or "")
    assert "huella" in compraventa.a_registro()["campos"]["naturaleza"]
    assert "Pérez" not in str(compraventa.a_registro())

    p = {k: v.valor for k, v in poder.campos.items()}
    assert p["categoria"] == "ACTA_O_PODER"
    assert p["base_imponible"] == "0.00"
    assert [a.codigo for a in poder.alertas] == ["NUMERO_YA_DECLARADO"]

    h = {k: v.valor for k, v in hipoteca.campos.items()}
    assert h["tipo_protocolo"] == "AUXILIAR"
    assert "FECHA_FUERA_DEL_PERIODO" in [a.codigo for a in hipoteca.alertas]


def test_renglones_de_ocr() -> None:
    texto = """INDICE DEL PROTOCOLO 2026
N°  FECHA       NATURALEZA       PARTES                 FOLIO  MONTO
120 14/09/2026  Compraventa      Pérez Juan a Gómez Ana   345   $ 45.000.000,00
121 15/09/2026  Poder general    Ruiz Marta a Ruiz Pedro  348
total del mes"""
    renglones = indice.renglones_de_ocr(texto, 2)
    assert [(r.numero, r.folio, r.monto) for r in renglones] == [
        ("120", "345", "45.000.000,00"),
        ("121", "348", None),
    ]
    assert renglones[0].naturaleza == "Compraventa"
    assert renglones[0].foto == 2


def test_sin_configurar_no_sale_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "IA_VISION_PROVEEDOR", "deepseek")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", SecretStr("   "))
    assert vision.configurada() is False
    monkeypatch.setattr(settings, "IA_VISION_PROVEEDOR", "local")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", SecretStr("clave"))
    assert vision.configurada() is False


def test_la_foto_sale_sin_metadatos() -> None:
    original = io.BytesIO()
    imagen = Image.new("RGB", (3000, 1500), "white")
    exif = Image.Exif()
    exif[0x010F] = "Fabricante del celular"
    imagen.save(original, "JPEG", exif=exif.tobytes())
    archivo = ArchivoValidado(original.getvalue(), "image/jpeg", "jpg", "x", "f.jpg")
    jpeg = lectura._foto_para_vision(archivo)
    enviada = Image.open(io.BytesIO(jpeg))
    assert max(enviada.size) == lectura.LADO_MAXIMO_VISION
    assert not enviada.getexif()


# --------------------------------------------------------------------------- API


async def test_foto_del_indice_sugiere_un_acto_por_renglon(
    notario: AsyncClient,
    escenario: Escenario,
    borrador: dict[str, Any],
    con_vision: list[bytes],
    db_session: AsyncSession,
) -> None:
    respuesta = await notario.post(
        "/api/v1/ia/indices", data={"ddjj_id": borrador["id"]}, files=_fotos()
    )
    assert respuesta.status_code == 201, respuesta.text
    body = respuesta.json()
    assert body["motor"] == "indice-vision-deepseek"
    assert len(con_vision) == 1
    sugerencias = body["sugerencias"]
    assert [s["campos"]["numero_escritura"]["valor"] for s in sugerencias] == ["120", "121", "122"]
    assert {s["tipo"] for s in sugerencias} == {"EXTRACCION_INDICE"}
    assert [s["entrada"]["renglon"] for s in sugerencias] == [1, 2, 3]
    # Analizar no escribe actos.
    actos = await db_session.scalars(select(Acto).where(Acto.ddjj_id == uuid.UUID(borrador["id"])))
    assert actos.all() == []
    # Queda registrado en el backend qué proveedor procesó las fotos.
    registro = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "IA_INDICE_LEIDO")
    )
    assert registro is not None and registro.details is not None
    assert registro.details["procesamiento_externo"] == "deepseek"
    assert registro.details["renglones"] == 3

    # Cada renglón se ratifica como un acto, por el camino de la carga manual.
    primero = sugerencias[0]
    ratificado = await notario.post(
        f"/api/v1/ia/sugerencias/{primero['id']}/ratificar-acto",
        json=_cuerpo(primero, escenario.titular.id),
    )
    assert ratificado.status_code == 200, ratificado.text
    assert ratificado.json()["acto"]["numero_escritura"] == 120
    assert ratificado.json()["acto"]["base_imponible"] == "45000000.00"
    # Con la fecha fuera del período, la carga lo rechaza igual que a mano.
    tercero = sugerencias[2]
    fuera = await notario.post(
        f"/api/v1/ia/sugerencias/{tercero['id']}/ratificar-acto",
        json=_cuerpo(tercero, escenario.titular.id),
    )
    assert fuera.status_code == 422


async def test_si_la_vision_falla_sigue_con_ocr_local(
    notario: AsyncClient,
    borrador: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "IA_VISION_PROVEEDOR", "deepseek")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", SecretStr("clave-de-prueba"))

    async def caida(_: bytes) -> vision.LecturaVision:
        raise vision.VisionNoDisponibleError("El proveedor respondió 503.")

    async def ocr(_: ArchivoValidado) -> str:
        return "120 14/09/2026  Compraventa  Pérez a Gómez  345  $ 45.000.000,00"

    monkeypatch.setattr(vision, "transcribir", caida)
    monkeypatch.setattr(lectura, "ocr_indice", ocr)
    respuesta = await notario.post(
        "/api/v1/ia/indices", data={"ddjj_id": borrador["id"]}, files=_fotos()
    )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["motor"] == "indice-ocr-tesseract"
    registro = await db_session.scalar(
        select(AuditSecurityLog).where(AuditSecurityLog.event_type == "IA_INDICE_LEIDO")
    )
    assert registro is not None and registro.details is not None
    assert registro.details["procesamiento_externo"] is None
    assert registro.details["respaldo_local"] == ["El proveedor respondió 503."]


async def test_limites_y_permisos(
    notario: AsyncClient,
    borrador: dict[str, Any],
    con_vision: list[bytes],
) -> None:
    demasiadas = await notario.post(
        "/api/v1/ia/indices",
        data={"ddjj_id": borrador["id"]},
        files=_fotos(get_settings().IA_INDICE_MAX_FOTOS + 1),
    )
    assert demasiadas.status_code == 422
    falsa = await notario.post(
        "/api/v1/ia/indices",
        data={"ddjj_id": borrador["id"]},
        files=[("archivos", ("indice.png", b"no es una imagen", "image/png"))],
    )
    assert falsa.status_code in (415, 422)
    assert con_vision == []


def test_montos_y_textos_desmesurados_no_rompen_la_lectura() -> None:
    enorme = "9" * 5000
    respuesta = f'[{{"numero": "120", "fecha": "14/09/2026", "naturaleza": "{"x" * 5000}", '
    respuesta += f'"monto": "$ {enorme}"}}, {{"numero": "121", "monto": {enorme}}}]'
    renglones = indice.renglones_de_vision(respuesta, 1)
    assert all(len(r.naturaleza or "") <= indice.MAX_CARACTERES_CAMPO for r in renglones)
    for r in renglones:
        resultado = indice.a_resultado(r, CTX, confianza=Decimal("0.85"))
        assert resultado.campos["base_imponible"].valor in (None, "0.00")
    # 16 enteros entran; 17 no.
    tope = indice.Renglon(numero="1", monto="9" * 16 + ",50")
    assert (
        indice.a_resultado(tope, CTX, confianza=Decimal("0.85")).campos["base_imponible"].valor
        == "9" * 16 + ".50"
    )
    pasado = indice.Renglon(numero="1", monto="9" * 17)
    assert indice.a_resultado(pasado, CTX, confianza=Decimal("0.85")).campos[
        "base_imponible"
    ].valor in (None, "0.00")
