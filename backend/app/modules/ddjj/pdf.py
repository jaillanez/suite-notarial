"""PDF oficiales (weasyprint): la boleta, con QR de verificación y código de barras Code128, y la
Declaración Jurada de Aportes con el formato de la planilla de la Caja."""

import base64
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import anyio
import barcode
import qrcode
from barcode.writer import SVGWriter
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from qrcode.image.svg import SvgPathImage

from app.common.dates import LOCAL_TZ
from app.common.money import format_pesos
from app.core.config import Settings
from app.modules.ddjj.models import Boleta
from app.modules.ddjj.schemas import PlanillaOut

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "boletas"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(enabled_extensions=("html",)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def fecha(valor: date) -> str:
    return valor.strftime("%d-%m-%Y")


def tasa(valor: Decimal, periodo: str) -> str:
    """4.2500, MENSUAL → "4,25 % mensual" (al menos dos decimales, sin ceros de más)."""
    texto = f"{valor:.4f}".rstrip("0")
    if len(texto.split(".")[1]) < 2:
        texto = f"{valor:.2f}"
    return f"{texto.replace('.', ',')} % {periodo.lower()}"


_env.filters["pesos"] = format_pesos
_env.filters["fecha"] = fecha
_env.filters["tasa"] = tasa


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


# --------------------------------------------------------------------------- DDJJ (planilla)

CARGO_PLANILLA = {"TITULAR": "Titular", "ADSCRIPTO": "Adscripto", "SUPLENTE_INTERINO": "A cargo"}
PROTOCOLO_PLANILLA = {"GENERAL": "Protocolo General", "AUXILIAR": "Protocolo Auxiliar"}
MOTIVO_EXENCION_PLANILLA = {
    "CONVENIO_IPV": "Emanada del IPV",
    "ACTA_SUBSANATORIA": "Acta subsanatoria",
    "REGULACION_DOMINIAL": "Acta de regulación dominial",
    "ASOCIACION_INTERMEDIA_IPV": "Asociación intermedia con hipoteca a favor del IPV",
    "OTRO": "Otro motivo",
}


def render_planilla_html(settings: Settings, datos: PlanillaOut) -> str:
    generada = datetime.now(LOCAL_TZ)
    presentada = datos.fecha_presentacion.astimezone(LOCAL_TZ) if datos.fecha_presentacion else None
    return _env.get_template("ddjj.html").render(
        d=datos,
        caja=settings,
        periodo=f"{datos.periodo[5:7]}/{datos.periodo[:4]}",
        mes=datos.periodo[5:7],
        anio=datos.periodo[:4],
        generada=generada.strftime("%d-%m-%Y %H:%M"),
        presentada=presentada.strftime("%d-%m-%Y %H:%M") if presentada else None,
        cargo=CARGO_PLANILLA,
        protocolo=PROTOCOLO_PLANILLA,
        motivo_exencion=MOTIVO_EXENCION_PLANILLA,
    )


def render_planilla_pdf(settings: Settings, datos: PlanillaOut) -> bytes:
    from weasyprint import HTML

    html = render_planilla_html(settings, datos)
    contenido: bytes | None = HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()
    assert contenido is not None  # noqa: S101 - sin destino, write_pdf devuelve los bytes
    return contenido


async def render_planilla_pdf_async(settings: Settings, datos: PlanillaOut) -> bytes:
    return await anyio.to_thread.run_sync(render_planilla_pdf, settings, datos)
