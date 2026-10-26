"""Guardas estáticas de reglas innegociables (FIN, SEC-04)."""

import io
import re
import tokenize
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# FIN: archivos con lógica monetaria. Se amplía a medida que se agregan módulos financieros.
MONEY_PATHS = ["common/money.py"]
MONEY_DIR_HINTS = (
    "aportes",
    "boletas",
    "pagos",
    "prestamos",
    "liquidacion",
    "parametros",
    "ia",
)

_PRIVATE_URL_RE = re.compile(
    r"https?://(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|0\.0\.0\.0)",
    re.IGNORECASE,
)


def _money_files() -> list[Path]:
    files = [APP_DIR / p for p in MONEY_PATHS]
    for path in APP_DIR.rglob("*.py"):
        if any(hint in path.parts for hint in MONEY_DIR_HINTS):
            files.append(path)
    return files


def _float_lines(path: Path) -> list[int]:
    """Líneas con el nombre `float`, según el tokenizador real (ignora comentarios y strings)."""
    source = path.read_text(encoding="utf-8")
    return [
        tok.start[0]
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.NAME and tok.string == "float"
    ]


def test_no_float_in_money_logic() -> None:
    offenders = [
        f"{path.relative_to(APP_DIR)}:{n}" for path in _money_files() for n in _float_lines(path)
    ]
    assert not offenders, f"Uso de float en lógica monetaria: {offenders}"


def test_mail_templates_have_no_private_urls() -> None:
    template_files = [
        p
        for p in APP_DIR.rglob("*")
        if p.is_file() and "templates" in p.parts and p.suffix in {".html", ".txt", ".j2"}
    ]
    offenders = [
        str(p.relative_to(APP_DIR))
        for p in template_files
        if _PRIVATE_URL_RE.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"Plantillas con URLs privadas (usar PUBLIC_WEB_URL): {offenders}"
