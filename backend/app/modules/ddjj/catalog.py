"""Valores de dominio de declaraciones juradas y boletas (Módulo 5)."""

from enum import StrEnum


class CategoriaActo(StrEnum):
    """Cómo aporta un acto. Relevado del sistema en uso (reporte mensual 08/2026)."""

    # Escritura con valor: porcentaje sobre la base imponible, con mínimo y tope.
    ESCRITURA_CON_VALOR = "ESCRITURA_CON_VALOR"
    # Actas y poderes: aporte fijo por acto.
    ACTA_O_PODER = "ACTA_O_PODER"
    # Otros actos sin base imponible: aporte fijo por acto.
    OTRO_ACTO = "OTRO_ACTO"
    # Escritura que quedó sin efecto: se declara para no dejar huecos en la numeración, sin aporte.
    SIN_EFECTO = "SIN_EFECTO"


class TipoProtocolo(StrEnum):
    GENERAL = "GENERAL"
    AUXILIAR = "AUXILIAR"


class EstadoDDJJ(StrEnum):
    BORRADOR = "BORRADOR"
    PRESENTADA = "PRESENTADA"
    RECTIFICADA = "RECTIFICADA"


class EstadoBoleta(StrEnum):
    PENDIENTE = "PENDIENTE"
    PAGADA = "PAGADA"
    ANULADA = "ANULADA"


# Concepto del motor paramétrico que liquida cada categoría (Fase 3).
CONCEPTO_POR_CATEGORIA: dict[CategoriaActo, str | None] = {
    CategoriaActo.ESCRITURA_CON_VALOR: "APORTE_ESCRITURA",
    CategoriaActo.ACTA_O_PODER: "APORTE_FIJO_ACTAS_PODERES",
    CategoriaActo.OTRO_ACTO: "APORTE_FIJO_OTROS_ACTOS",
    CategoriaActo.SIN_EFECTO: None,
}
CONCEPTO_MINIMO = "APORTE_MINIMO_MENSUAL"
CONCEPTO_MEDICO = "APORTE_MEDICO_ASISTENCIAL"
CONCEPTO_MORA = "TASA_INTERES_MORA"
