"""Interpretación de los valores tal como los exporta un sistema anterior.

Nada se redondea ni se adivina en silencio: lo que no se puede interpretar sin ambigüedad lanza
`ValorInvalidoError` con el motivo, que la validación convierte en observación (regla FIN para
importes: texto → `Decimal` exacto, nunca `float`).
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

CENTAVO = Decimal("0.01")


class ValorInvalidoError(ValueError):
    pass


_FECHAS = (
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), (1, 2, 3)),
    (re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})"), (3, 2, 1)),
    (re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})"), (3, 2, 1)),
)


def fecha(valor: str) -> date:
    """aaaa-mm-dd, dd/mm/aaaa o dd-mm-aaaa (con hora opcional, que se descarta)."""
    texto = valor.strip().split(" ")[0].split("T")[0]
    for patron, (a, m, d) in _FECHAS:
        coincide = patron.fullmatch(texto)
        if coincide:
            try:
                return date(int(coincide.group(a)), int(coincide.group(m)), int(coincide.group(d)))
            except ValueError as exc:
                raise ValorInvalidoError("fecha inexistente") from exc
    raise ValorInvalidoError("fecha con formato desconocido")


_PERIODOS = (
    (re.compile(r"(\d{4})-(\d{1,2})"), 1, 2),
    (re.compile(r"(\d{1,2})/(\d{4})"), 2, 1),
    (re.compile(r"(\d{4})(\d{2})"), 1, 2),
)


def periodo(valor: str) -> str:
    """aaaa-mm, mm/aaaa o aaaamm → "aaaa-mm"."""
    texto = valor.strip()
    for patron, a, m in _PERIODOS:
        coincide = patron.fullmatch(texto)
        if coincide:
            anio, mes = int(coincide.group(a)), int(coincide.group(m))
            if 1 <= mes <= 12 and 1900 <= anio <= 2100:
                return f"{anio:04d}-{mes:02d}"
    raise ValorInvalidoError("período con formato desconocido")


_MILES_CON_PUNTO = re.compile(r"\d{1,3}(\.\d{3})+")
_MILES_CON_COMA = re.compile(r"\d{1,3}(,\d{3})+")


def importe(valor: str) -> Decimal:
    """Importe del origen ("1.234,50", "1234,5", "1,234.50", "$ 1.234") → Decimal exacto.

    Si hay punto y coma, el último es el decimal. Con un solo separador repetido o seguido de
    tres dígitos exactos (p. ej. "1.234"), es de miles. Más de dos decimales con dígitos
    distintos de cero (típico de un `float` del origen) es un error: no se redondea.
    """
    texto = valor.strip().replace("$", "").replace(" ", "").replace(" ", "")
    if not texto:
        raise ValorInvalidoError("importe vacío")
    negativo = texto.startswith("-")
    texto = texto.lstrip("-")
    if "," in texto and "." in texto:
        decimal_sep = "," if texto.rfind(",") > texto.rfind(".") else "."
        miles = "." if decimal_sep == "," else ","
        texto = texto.replace(miles, "").replace(decimal_sep, ".")
    elif _MILES_CON_PUNTO.fullmatch(texto):
        texto = texto.replace(".", "")
    elif _MILES_CON_COMA.fullmatch(texto):
        texto = texto.replace(",", "")
    else:
        texto = texto.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", texto):
        raise ValorInvalidoError("importe ilegible")
    try:
        numero = Decimal(texto)
    except InvalidOperation as exc:
        raise ValorInvalidoError("importe ilegible") from exc
    if numero != numero.quantize(CENTAVO):
        raise ValorInvalidoError(
            "importe con más de dos decimales (posible valor de punto flotante en el "
            "origen): no se redondea"
        )
    return (-numero if negativo else numero).quantize(CENTAVO)


def entero(valor: str) -> int:
    texto = valor.strip()
    if not re.fullmatch(r"\d{1,9}", texto):
        raise ValorInvalidoError("número entero inválido")
    return int(texto)


def texto(valor: str, maximo: int) -> str:
    limpio = " ".join(valor.split())
    if len(limpio) > maximo:
        raise ValorInvalidoError(f"texto de más de {maximo} caracteres")
    return limpio
