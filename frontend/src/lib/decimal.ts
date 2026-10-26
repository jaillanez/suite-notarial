/**
 * Formato de importes y tasas a partir del texto decimal que envía la API.
 * Nunca se convierte a `number`: los montos no pasan por punto flotante (regla FIN).
 */

const DECIMAL_RE = /^(-?)(\d+)(?:\.(\d+))?$/

function group(integer: string): string {
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
}

/** "1234567.5" → "1.234.567,50" (dos decimales, separadores es-AR). */
export function formatDecimal(value: string, decimals = 2): string {
  const match = DECIMAL_RE.exec(value.trim())
  if (!match) return value
  const [, sign = '', integer = '0', fraction = ''] = match
  const frac = fraction.padEnd(decimals, '0').slice(0, decimals)
  return `${sign}${group(integer.replace(/^0+(?=\d)/, ''))}${decimals > 0 ? `,${frac}` : ''}`
}

/** "-1500.5" → "−$ 1.500,50": el signo va antes del símbolo. */
export function formatMoney(value: string | null): string {
  if (value === null) return '—'
  const formatted = formatDecimal(value, 2)
  return formatted.startsWith('-') ? `−$ ${formatted.slice(1)}` : `$ ${formatted}`
}

/** Porcentaje sin ceros finales innecesarios: "1.5000" → "1,5 %". */
export function formatPercent(value: string | null): string {
  if (value === null) return '—'
  const formatted = formatDecimal(value, 4).replace(/,?0+$/, '')
  return `${formatted} %`
}

/**
 * Importe tipeado en es-AR → texto decimal: "1.234,56" → "1234.56", "1.500.000" → "1500000",
 * "450.000" → "450000". Un importe no tiene tres decimales, así que un punto seguido de grupos
 * de tres dígitos es siempre separador de miles. Para tasas usar `normalizeTasaInput`.
 */
export function normalizeDecimalInput(value: string): string {
  const trimmed = value.trim().replace(/\s/g, '')
  if (trimmed.includes(',')) return trimmed.replace(/\./g, '').replace(',', '.')
  if (/^\d{1,3}(\.\d{3})+$/.test(trimmed)) return trimmed.replace(/\./g, '')
  return trimmed
}

/** Tasa o porcentaje tipeado ("1,5" o "12.125") → texto decimal, sin regla de miles. */
export function normalizeTasaInput(value: string): string {
  const trimmed = value.trim().replace(/\s/g, '')
  if (trimmed.includes(',')) return trimmed.replace(/\./g, '').replace(',', '.')
  return trimmed
}

/** Signo de `a - b` para dos decimales en texto ("30.0001" vs "30"), sin pasar por float. */
export function compararDecimal(a: string, b: string): number {
  const partes = (v: string): [boolean, string, string] => {
    const negativo = v.trim().startsWith('-')
    const [entero = '0', fraccion = ''] = v.trim().replace(/^[-+]/, '').split('.')
    return [negativo, entero, fraccion]
  }
  const [an, ae, af] = partes(a)
  const [bn, be, bf] = partes(b)
  const largo = Math.max(af.length, bf.length)
  const ai = BigInt(ae + af.padEnd(largo, '0')) * (an ? -1n : 1n)
  const bi = BigInt(be + bf.padEnd(largo, '0')) * (bn ? -1n : 1n)
  return ai === bi ? 0 : ai > bi ? 1 : -1
}
