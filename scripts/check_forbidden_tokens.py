#!/usr/bin/env python3
"""Hook de pre-commit: bloquea `print(` en código de aplicación y `float` en módulos monetarios.

Usa el tokenizador de CPython: comentarios y literales de texto se clasifican con la
gramática real, así un `#` dentro de un string no oculta el resto de la línea.
"""

import io
import sys
import tokenize
from pathlib import Path

# Rutas consideradas lógica monetaria (regla FIN). Mantener en sync con backend/tests/test_guards.py.
MONEY_HINTS = ("money", "aportes", "boletas", "pagos", "prestamos", "liquidacion", "parametros")


def check(path: Path) -> list[str]:
    if not path.is_file():
        return [f"{path}: el archivo no existe"]
    if "app" not in path.parts:
        return []
    is_money = any(hint in part for part in path.parts for hint in MONEY_HINTS)
    source = path.read_text(encoding="utf-8")
    try:
        tokens = [
            t
            for t in tokenize.generate_tokens(io.StringIO(source).readline)
            if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT)
        ]
    except (tokenize.TokenError, SyntaxError) as exc:
        return [f"{path}: no se pudo tokenizar ({exc})"]

    errors: list[str] = []
    for i, tok in enumerate(tokens):
        if tok.type != tokenize.NAME:
            continue
        prev = tokens[i - 1] if i > 0 else None
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        is_attribute = prev is not None and prev.string == "."
        if tok.string == "print" and not is_attribute and nxt is not None and nxt.string == "(":
            errors.append(f"{path}:{tok.start[0]}: print( no permitido; usar logging")
        if is_money and tok.string == "float":
            errors.append(f"{path}:{tok.start[0]}: float prohibido en lógica monetaria; usar Decimal")
    return errors


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write("No se recibieron archivos para revisar.\n")
        return 2
    errors = [e for arg in argv for e in check(Path(arg))]
    for e in errors:
        sys.stderr.write(e + "\n")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
