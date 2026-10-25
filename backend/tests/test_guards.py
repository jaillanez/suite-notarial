"""Guardas estáticas de reglas innegociables (FIN, SEC-04)."""

import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# FIN: archivos con lógica monetaria. Se amplía a medida que se agregan módulos financieros.
MONEY_PATHS = ["common/money.py"]
MONEY_DIR_HINTS = ("aportes", "boletas", "pagos", "prestamos", "liquidacion", "parametros")

_FLOAT_RE = re.compile(r"\bfloat\b")
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


def _code_lines(path: Path) -> list[tuple[int, str]]:
    lines = []
    in_docstring = False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.count('"""') == 1:
            in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith(("#", '"""')):
            continue
        lines.append((n, line.split("#", 1)[0]))
    return lines


def test_no_float_in_money_logic() -> None:
    offenders = [
        f"{path.relative_to(APP_DIR)}:{n}"
        for path in _money_files()
        for n, code in _code_lines(path)
        if _FLOAT_RE.search(code)
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
