"""Migración del sistema anterior y puesta en marcha (Fase 10, módulo 11).

Flujo: lote de extracción (formato de intercambio) → staging en memoria → validación con
observaciones → carga transaccional → cuadratura al centavo contra los totales de control del
origen. Los simulacros se revierten; la carga definitiva exige simulacros que cuadren y la
conformidad de Tesorería y de Caja. Nada se fuerza ni se balancea: toda diferencia queda
explicada por una observación.
"""
