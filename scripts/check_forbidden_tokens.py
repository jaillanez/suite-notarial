#!/usr/bin/env python3
"""Hook de pre-commit: bloquea `print(` en código de aplicación y `float` en módulos monetarios."""

import re
import sys
from pathlib import Path

PRINT_RE = re.compile(r"(?<![\w.])print\(")
FLOAT_RE = re.compile(r"\bfloat\b")
# Rutas consideradas lógica monetaria (regla FIN). Mantener en sync con backend/tests/test_guards.py.
MONEY_HINTS = ("money", "aportes", "boletas", "pagos", "prestamos", "liquidacion", "parametros")


def _strip_comment(line: str) -> str:
    return line.split("#", 1)[0]


def check(path: Path) -> list[str]:
    errors: list[str] = []
    parts = path.parts
    if "app" not in parts:
        return errors
    is_money = any(hint in part for part in parts for hint in MONEY_HINTS)
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        code = _strip_comment(raw)
        if PRINT_RE.search(code):
            errors.append(f"{path}:{n}: print( no permitido; usar logging")
        if is_money and FLOAT_RE.search(code):
            errors.append(f"{path}:{n}: float prohibido en lógica monetaria; usar Decimal")
    return errors


def main(argv: list[str]) -> int:
    errors = [e for arg in argv for e in check(Path(arg))]
    for e in errors:
        sys.stderr.write(e + "\n")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
