import { describe, expect, it } from 'vitest'

import type { Linea } from './api'
import { fueraDeLinea, topeCapital, topeCuotas } from './labels'

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

describe('topes de la línea al tipear (pedido de la Caja, 23/11/2026)', () => {
  it('el capital nunca supera el máximo', () => {
    expect(topeCapital(LINEA, '600000')).toBe(LINEA.monto_maximo)
    expect(topeCapital(LINEA, '499999.99')).toBe('499999.99')
    expect(topeCapital(undefined, '9999999')).toBe('9999999')
  })

  it('las cuotas nunca superan el plazo máximo', () => {
    expect(topeCuotas(LINEA, '36')).toBe('24')
    expect(topeCuotas(LINEA, '1x2')).toBe('12')
    expect(topeCuotas(LINEA, '')).toBe('')
  })
})
