"""Escenario de IA asistencial: una DDJJ en borrador, minutas sintéticas y DNI sintéticos.

Todos los documentos se generan acá (texto, imágenes y códigos PDF417): ningún dato real.
"""

# Las fixtures se importan para reusarlas; ruff las ve como redefiniciones.
# ruff: noqa: F811

import io
from datetime import date
from typing import Any

import pytest
import zxingcpp
from httpx import AsyncClient
from PIL import Image, ImageDraw, ImageFont

from app.modules.ia import service as ia_service
from tests.ddjj.conftest import (  # noqa: F401 - fixtures compartidas
    HOY,
    Escenario,
    escenario,
    hoy,
    notario,
    parametros_2026,
    staff,
)
from tests.reportes.conftest import auditor  # noqa: F401 - fixture compartida


@pytest.fixture(autouse=True)
def hoy_ia(monkeypatch: pytest.MonkeyPatch, hoy: date) -> None:
    monkeypatch.setattr(ia_service, "today_local", lambda: HOY)


@pytest.fixture
async def borrador(notario: AsyncClient, escenario: Escenario) -> dict[str, Any]:
    """DDJJ 09/2026 del registro del escenario, en borrador."""
    response = await notario.post(
        "/api/v1/ddjj/declaraciones",
        json={"registro_id": str(escenario.registro.id), "periodo": "2026-09"},
    )
    assert response.status_code in (200, 201), response.text
    body: dict[str, Any] = response.json()
    return body


def minuta(escenario: Escenario, **cambios: str) -> str:
    """Minuta sintética de compraventa autorizada por el titular del registro."""
    datos = {
        "numero": "CIENTO VEINTE (120)",
        "fecha": "a los catorce días del mes de septiembre del año dos mil veintiséis",
        "precio": "PESOS CUARENTA Y CINCO MILLONES ($ 45.000.000,00)",
        "cargo": "titular",
        "extra": "",
        **cambios,
    }
    return (
        f"ESCRITURA NÚMERO {datos['numero']}. FOLIO 345. COMPRAVENTA. En la Ciudad de San Juan, "
        f"{datos['fecha']}, ante mí, Escribano {datos['cargo']} del Registro Notarial número "
        f"{escenario.registro.numero_registro}, matrícula {escenario.titular.matricula_numero}, "
        "comparecen Juan Carlos Sintético, CUIT 20-12345678-6, y Ana Prueba, CUIL 27-11111111-0, "
        f"personas capaces. {datos['extra']} El vendedor dice que VENDE al comprador un inmueble "
        f"por el precio total de {datos['precio']}, que recibe en este acto."
    )


def imagen_texto(texto: str, ancho: int = 1700) -> bytes:
    """PNG con el texto dibujado en renglones (para el OCR)."""
    fuente = ImageFont.load_default(size=26)
    palabras, renglones, actual = texto.split(), [], ""
    for palabra in palabras:
        if len(actual) + len(palabra) > 95:
            renglones.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}".strip()
    renglones.append(actual)
    imagen = Image.new("L", (ancho, 60 + 44 * len(renglones)), 255)
    dibujo = ImageDraw.Draw(imagen)
    for i, renglon in enumerate(renglones):
        dibujo.text((30, 30 + i * 44), renglon, fill=0, font=fuente)
    salida = io.BytesIO()
    imagen.save(salida, "PNG")
    return salida.getvalue()


def pdf417_png(contenido: str) -> bytes:
    """Imagen del código PDF417 del frente de un DNI sintético."""
    codigo = zxingcpp.create_barcode(contenido, zxingcpp.BarcodeFormat.PDF417)
    pixeles = memoryview(codigo.to_image(scale=3))
    assert pixeles.shape is not None
    alto, ancho = pixeles.shape[0], pixeles.shape[1]
    imagen = Image.frombytes("L", (ancho, alto), pixeles.tobytes())
    lienzo = Image.new("L", (ancho + 80, alto + 80), 255)
    lienzo.paste(imagen, (40, 40))
    salida = io.BytesIO()
    lienzo.save(salida, "PNG")
    return salida.getvalue()


DNI_NUEVO = "00512345678@SINTETICO DE LA PRUEBA@JUAN CARLOS@M@12345678@B@15/03/1975@10/06/2020@200"
