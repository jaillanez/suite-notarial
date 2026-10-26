import { describe, expect, it } from 'vitest'

import {
  compararDecimal,
  formatDecimal,
  formatMoney,
  formatPercent,
  normalizeDecimalInput,
  normalizeTasaInput,
} from './decimal'

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

describe('compararDecimal', () => {
  it('compara sin float, con distinta cantidad de decimales y signo', () => {
    expect(compararDecimal('30.0001', '30')).toBe(1)
    expect(compararDecimal('30.0000', '30.00')).toBe(0)
    expect(compararDecimal('29.9999', '30.0000')).toBe(-1)
    expect(compararDecimal('-5.50', '1')).toBe(-1)
    expect(compararDecimal('0.1', '0.10000000000000001')).toBe(-1)
  })
})

describe('normalizeDecimalInput', () => {
  it('acepta la forma local con y sin coma decimal', () => {
    expect(normalizeDecimalInput('1.234,56')).toBe('1234.56')
    expect(normalizeDecimalInput('1.500.000')).toBe('1500000')
    expect(normalizeDecimalInput('1234.56')).toBe('1234.56')
    // Un importe no tiene tres decimales: "450.000" son 450 mil.
    expect(normalizeDecimalInput('450.000')).toBe('450000')
    expect(normalizeDecimalInput('0.50')).toBe('0.50')
    expect(normalizeTasaInput('12.125')).toBe('12.125')
    expect(normalizeTasaInput('1,5')).toBe('1.5')
  })
})
