"""Boleta oficial en PDF (weasyprint) con QR de verificación y código de barras Code128."""

import base64
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import anyio
import barcode
import qrcode
from barcode.writer import SVGWriter
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from qrcode.image.svg import SvgPathImage

from app.core.config import Settings
from app.modules.ddjj.models import Boleta

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "boletas"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(enabled_extensions=("html",)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def pesos(monto: Decimal) -> str:
    """`$ 1.081.699,06`: formato argentino sin pasar por float."""
    signo = "-" if monto < 0 else ""
    entero, _, centavos = f"{abs(monto):.2f}".partition(".")
    grupos: list[str] = []
    while entero:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    return f"{signo}$ {'.'.join(grupos)},{centavos}"


def fecha(valor: date) -> str:
    return valor.strftime("%d-%m-%Y")


_env.filters["pesos"] = pesos
_env.filters["fecha"] = fecha


def url_verificacion(settings: Settings, codigo: str) -> str:
    return f"{settings.public_web_base}/verificar/{codigo}"


def contenido_codigo_barras(boleta: Boleta) -> str:
    """Número de boleta y código de verificación.

    TODO(negocio): el formato de cobranza que exija el banco recaudador (Supervielle) puede
    requerir otro contenido (importe, vencimiento, dígito verificador).
    """
    return f"{boleta.numero:010d}{boleta.codigo_verificacion}"


def qr_svg(contenido: str) -> str:
    img = qrcode.make(contenido, image_factory=SvgPathImage, box_size=10, border=0)
    buffer = io.BytesIO()
    img.save(buffer)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def barcode_svg(contenido: str) -> str:
    buffer = io.BytesIO()
    barcode.get("code128", contenido, writer=SVGWriter()).write(
        buffer, options={"module_height": 12.0, "quiet_zone": 2.0, "write_text": False}
    )
    return base64.b64encode(buffer.getvalue()).decode("ascii")


@dataclass(frozen=True)
class EscribanoBoleta:
    apellido_nombre: str
    cargo: str


@dataclass(frozen=True)
class DatosBoleta:
    boleta: Boleta
    registro_numero: int
    numero_rectificativa: int
    escribanos: list[EscribanoBoleta]


def render_html(settings: Settings, datos: DatosBoleta) -> str:
    boleta = datos.boleta
    verificacion = url_verificacion(settings, boleta.codigo_verificacion)
    barras = contenido_codigo_barras(boleta)
    return _env.get_template("boleta.html").render(
        b=boleta,
        registro=datos.registro_numero,
        periodo=f"{boleta.periodo[5:7]}/{boleta.periodo[:4]}",
        rectificativa=datos.numero_rectificativa,
        escribanos=datos.escribanos,
        caja=settings,
        verificacion=verificacion,
        qr=qr_svg(verificacion),
        barras=barcode_svg(barras),
        barras_texto=barras,
        codigo=" ".join(boleta.codigo_verificacion[i : i + 4] for i in range(0, 16, 4)),
    )


def render_pdf(settings: Settings, datos: DatosBoleta) -> bytes:
    # Import diferido: weasyprint carga librerías nativas (pango) al importarse.
    from weasyprint import HTML

    html = render_html(settings, datos)
    pdf: bytes | None = HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()
    assert pdf is not None  # noqa: S101 - sin destino, write_pdf devuelve los bytes
    return pdf


async def render_pdf_async(settings: Settings, datos: DatosBoleta) -> bytes:
    """weasyprint es sincrónico y pesado: corre en un hilo para no frenar el event loop."""
    return await anyio.to_thread.run_sync(render_pdf, settings, datos)
