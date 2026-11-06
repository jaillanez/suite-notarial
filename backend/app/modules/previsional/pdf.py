"""«Informe de aportes y puntos» en PDF: equivalente al «Informe para Escribano» de la Caja."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import anyio
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.common.money import format_pesos
from app.core.config import Settings
from app.modules.previsional.service import Informe

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "previsional"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(enabled_extensions=("html",)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def formato_puntos(valor: Decimal) -> str:
    """97.639503 → «97,639503» (6 decimales, miles con punto), sin pasar por float."""
    entero, _, decimales = f"{abs(valor):.6f}".partition(".")
    grupos: list[str] = []
    while entero:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    return f"{'-' if valor < 0 else ''}{'.'.join(grupos)},{decimales}"


def _fecha(valor: date) -> str:
    return valor.strftime("%d/%m/%Y")


def render_html(settings: Settings, informe: Informe, emitido: date) -> str:
    e = informe.escribano
    return _env.get_template("informe_puntos.html").render(
        caja=settings,
        emitido=_fecha(emitido),
        e={
            "apellido_nombre": f"{e.persona.apellido}, {e.persona.nombre}",
            "matricula_numero": e.matricula_numero,
            "tipo_documento": e.persona.tipo_documento,
            "numero_documento": e.persona.numero_documento,
        },
        filas=[
            {
                "anio": f.anio,
                "fecha_inicio": _fecha(f.fecha_inicio),
                "fecha_cierre": _fecha(f.fecha_cierre),
                "aportes": format_pesos(f.aportes),
                "puntos": formato_puntos(f.puntos),
            }
            for f in informe.filas
        ],
        total_aportes=format_pesos(informe.total_aportes),
        total_puntos=formato_puntos(informe.total_puntos),
        origen="; ".join(informe.fuentes) or f"los registros de la {settings.CAJA_NOMBRE}",
    )


def render_pdf(settings: Settings, informe: Informe, emitido: date) -> bytes:
    # Import diferido: weasyprint carga librerías nativas (pango) al importarse.
    from weasyprint import HTML

    html = render_html(settings, informe, emitido)
    pdf: bytes | None = HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()
    assert pdf is not None  # noqa: S101 - sin destino, write_pdf devuelve los bytes
    return pdf


async def render_pdf_async(settings: Settings, informe: Informe, emitido: date) -> bytes:
    """weasyprint es sincrónico y pesado: corre en un hilo para no frenar el event loop."""
    return await anyio.to_thread.run_sync(render_pdf, settings, informe, emitido)
