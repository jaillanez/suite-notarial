"""Teléfono de contacto: solo dígitos y los separadores habituales, con una cantidad razonable.

Se acepta como se escribe en la Argentina (`264 427-6426`, `(0264) 4276426`, `+54 9 264 427 6426`)
y se guarda tal cual, sin espacios de más. Lo que no es un teléfono (letras, símbolos) se rechaza.
"""

import re
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

# Un número argentino tiene 10 dígitos sin el 0 ni el 15; con el +54 9 o el 0 de larga
# distancia llega a 13. E.164 admite hasta 15.
MIN_DIGITOS = 8
MAX_DIGITOS = 15
_PERMITIDOS = re.compile(r"^\+?[\d\s().-]+$")


def validar_telefono(valor: str) -> str:
    valor = " ".join(valor.split())
    if not valor:
        return valor
    if not _PERMITIDOS.fullmatch(valor) or "+" in valor[1:]:
        raise ValueError(
            "El teléfono lleva solo números (puede tener +, espacios, guiones o paréntesis)."
        )
    digitos = sum(c.isdigit() for c in valor)
    if not MIN_DIGITOS <= digitos <= MAX_DIGITOS:
        raise ValueError(
            f"El teléfono tiene que tener entre {MIN_DIGITOS} y {MAX_DIGITOS} números, con la "
            "característica (por ejemplo, 264 427-6426)."
        )
    return valor


Telefono = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=30), AfterValidator(validar_telefono)
]
