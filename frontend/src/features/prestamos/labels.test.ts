import { describe, expect, it } from 'vitest'

import type { Linea } from './api'
import { fueraDeLinea } from './labels'

const LINEA = {
  monto_minimo: '1000.00',
  monto_maximo: '500000.00',
  plazo_minimo: 1,
  plazo_maximo: 24,
  moneda: 'ARS',
} as Linea

describe('topes de la línea', () => {
  it('el capital y las cuotas no pasan de lo que fija la línea', () => {
    expect(fueraDeLinea(LINEA, '500000', 24)).toEqual({})
    expect(fueraDeLinea(LINEA, '500000.01', 12).capital).toMatch(/máximo/)
    expect(fueraDeLinea(LINEA, '999.99', 12).capital).toMatch(/mínimo/)
    expect(fueraDeLinea(LINEA, '10000', 25).cuotas).toBe('Hasta 24 cuotas.')
    // A medio tipear no se marca nada.
    expect(fueraDeLinea(LINEA, '', Number.NaN)).toEqual({})
  })
})
