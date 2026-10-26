from decimal import Decimal
from enum import StrEnum


class TipoSugerencia(StrEnum):
    # Minuta o borrador de escritura → acto de una DDJJ en borrador.
    EXTRACCION_MINUTA = "EXTRACCION_MINUTA"
    # Frente o dorso del DNI → datos personales para el alta de un escribano en el padrón.
    OCR_DNI = "OCR_DNI"


class EstadoSugerencia(StrEnum):
    SUGERIDO_POR_IA = "SUGERIDO_POR_IA"
    RATIFICADA = "RATIFICADA"
    DESCARTADA = "DESCARTADA"


class NivelAlerta(StrEnum):
    # Algo que probablemente esté mal y conviene corregir antes de ratificar.
    ADVERTENCIA = "ADVERTENCIA"
    # Información para la revisión (p. ej. un dato que no se pudo leer).
    AVISO = "AVISO"


# Motores locales y explicables (módulo 10 §1.1: sin "caja negra" en validaciones críticas y sin
# enviar datos a servicios externos). Cada sugerencia guarda nombre y versión del que la produjo.
MOTOR_MINUTA = "reglas-minuta"
MOTOR_MINUTA_VERSION = "1.0"
MOTOR_DNI_PDF417 = "dni-pdf417"
MOTOR_DNI_MRZ = "dni-mrz-tesseract"
MOTOR_DNI_VERSION = "1.0"

CONFIANZA_QUANT = Decimal("0.0001")
