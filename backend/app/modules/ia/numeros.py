"""Números escritos como en las escrituras: en letras ("ciento veinte") y montos en formato
argentino ("$ 45.000.000,00"). Todo en enteros y `Decimal` (regla FIN)."""

import re
from decimal import Decimal, InvalidOperation

# Traducción 1 a 1 (no cambia posiciones): permite buscar sin acentos y citar el texto original.
_SIN_ACENTOS = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")


def plano(texto: str) -> str:
    """Minúsculas y sin acentos, con la misma longitud que el original."""
    resultado = texto.translate(_SIN_ACENTOS).lower()
    if len(resultado) == len(texto):
        return resultado
    # `lower()` alarga algunos caracteres (p. ej. "İ"): se mapea de a uno para no correr posiciones.
    return "".join(_caracter(c) for c in texto)


def _caracter(c: str) -> str:
    bajo = c.translate(_SIN_ACENTOS).lower()
    return bajo if len(bajo) == 1 else c


_UNIDADES = {
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "primer": 1,
    "primero": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiun": 21,
    "veintiuno": 21,
    "veintiuna": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
    "ciento": 100,
    "doscientos": 200,
    "doscientas": 200,
    "trescientos": 300,
    "trescientas": 300,
    "cuatrocientos": 400,
    "cuatrocientas": 400,
    "quinientos": 500,
    "quinientas": 500,
    "seiscientos": 600,
    "seiscientas": 600,
    "setecientos": 700,
    "setecientas": 700,
    "ochocientos": 800,
    "ochocientas": 800,
    "novecientos": 900,
    "novecientas": 900,
}
_MILLON = frozenset({"millon", "millones"})
PALABRA_NUMERO = re.compile(r"[a-z]+")


_EXACTAS = frozenset({*_UNIDADES, *_MILLON, "mil", "y"})


def _una_diferencia(a: str, b: str) -> bool:
    """Distancia de edición 1 (una letra cambiada, de más o de menos)."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    corta, larga = (a, b) if len(a) < len(b) else (b, a)
    return any(larga[:i] + larga[i + 1 :] == corta for i in range(len(larga)))


def normalizar_palabra(palabra: str) -> str | None:
    """La palabra numérica que es, tolerando una letra mal leída por OCR en palabras largas
    ("veintisXis" → "veintiseis"). `None` si no es un número."""
    if palabra in _EXACTAS:
        return palabra
    if len(palabra) < 5:
        return None
    parecidas = [c for c in _EXACTAS if len(c) >= 5 and _una_diferencia(palabra, c)]
    return parecidas[0] if len(parecidas) == 1 else None


def es_palabra_numero(palabra: str) -> bool:
    return normalizar_palabra(palabra) is not None


def palabras_a_entero(texto: str) -> int | None:
    """ "dos millones trescientos mil quinientos" → 2300500. `None` si no es un número en letras.

    Recibe texto ya pasado por `plano()`. Ignora palabras no numéricas al principio y al final.
    """
    palabras = [p for p in PALABRA_NUMERO.findall(texto)]
    while palabras and not es_palabra_numero(palabras[0]):
        palabras.pop(0)
    while palabras and not es_palabra_numero(palabras[-1]):
        palabras.pop()
    if not palabras or palabras[0] == "y":
        return None
    total = 0
    grupo = 0
    vio_numero = False
    for leida in palabras:
        palabra = normalizar_palabra(leida) or leida
        if palabra == "y":
            continue
        if palabra in _UNIDADES:
            grupo += _UNIDADES[palabra]
            vio_numero = True
        elif palabra == "mil":
            grupo = (grupo or 1) * 1000
            vio_numero = True
        elif palabra in _MILLON:
            total += (grupo or 1) * 1_000_000
            grupo = 0
            vio_numero = True
        else:
            return None
    return total + grupo if vio_numero else None


# Monto en cifras: miles con punto y decimales con coma ("45.000.000,00"), o sin separadores.
MONTO_CIFRAS = r"[0-9]{1,3}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?|[0-9]+(?:,[0-9]{1,2})?"


def monto_ar(cifras: str) -> Decimal | None:
    """ "45.000.000,50" → Decimal("45000000.50")."""
    try:
        valor = Decimal(cifras.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None
    return valor.quantize(Decimal("0.01"))


def monto_en_letras(texto: str) -> Decimal | None:
    """ "cuarenta y cinco millones con cincuenta centavos" → Decimal("45000000.50")."""
    partes = re.split(r"\bcon\b", texto, maxsplit=1)
    entero = palabras_a_entero(partes[0])
    if entero is None:
        return None
    centavos = 0
    if len(partes) == 2 and "centavo" in partes[1]:
        centavos = palabras_a_entero(partes[1].split("centavo")[0]) or 0
        if centavos > 99:
            return None
    return Decimal(entero) + Decimal(centavos) / 100
