"""Validación de CUIT/CUIL (dígito verificador Módulo 11, criterio AFIP)."""

import re

_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
_VALID_PREFIXES = frozenset({"20", "23", "24", "27", "30", "33", "34"})
_SEPARATORS = re.compile(r"[\s.\-/]")


class InvalidCuitError(ValueError):
    pass


def check_digit(first_ten: str) -> int | None:
    """Dígito verificador de los 10 primeros dígitos; `None` si da 10 (no asignable)."""
    total = sum(int(d) * w for d, w in zip(first_ten, _WEIGHTS, strict=True))
    result = 11 - (total % 11)
    if result == 11:
        return 0
    if result == 10:
        return None
    return result


def normalize_cuit(value: str) -> str:
    """Devuelve los 11 dígitos sin separadores o lanza `InvalidCuitError`."""
    digits = _SEPARATORS.sub("", value)
    if not digits.isdigit() or len(digits) != 11:
        raise InvalidCuitError("El CUIT debe tener 11 dígitos.")
    if digits[:2] not in _VALID_PREFIXES:
        raise InvalidCuitError("El prefijo del CUIT no es válido.")
    expected = check_digit(digits[:10])
    if expected is None or expected != int(digits[10]):
        raise InvalidCuitError("El dígito verificador del CUIT no es válido.")
    return digits


def format_cuit(digits: str) -> str:
    return f"{digits[:2]}-{digits[2:10]}-{digits[10]}"
