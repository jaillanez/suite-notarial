import { describe, expect, it } from 'vitest'

import { formatDecimal, formatMoney, formatPercent, normalizeDecimalInput } from './decimal'

describe('decimal', () => {
  it('formatea sin pasar por punto flotante', () => {
    expect(formatMoney('1234567.50')).toBe('$ 1.234.567,50')
    expect(formatMoney('0.1')).toBe('$ 0,10')
    // Un número que en float pierde precisión se formatea exacto.
    expect(formatDecimal('9007199254740993.01')).toBe('9.007.199.254.740.993,01')
  })

  it('formatea porcentajes sin ceros de más', () => {
    expect(formatPercent('1.5000')).toBe('1,5 %')
    expect(formatPercent('3.0000')).toBe('3 %')
    expect(formatPercent('0.1250')).toBe('0,125 %')
  })

  it('normaliza lo que tipea una persona', () => {
    expect(normalizeDecimalInput('1.234,56')).toBe('1234.56')
    expect(normalizeDecimalInput('1234.56')).toBe('1234.56')
    expect(normalizeDecimalInput(' 25 000,00 ')).toBe('25000.00')
  })
})
