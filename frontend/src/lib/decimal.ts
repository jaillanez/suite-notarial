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

/** Acepta lo que tipea una persona en es-AR ("1.234,56" o "1234.56") y lo normaliza. */
export function normalizeDecimalInput(value: string): string {
  const trimmed = value.trim().replace(/\s/g, '')
  if (trimmed.includes(',')) return trimmed.replace(/\./g, '').replace(',', '.')
  return trimmed
}
