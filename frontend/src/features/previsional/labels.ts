import { formatDecimal } from '../../lib/decimal'

/** Puntos con sus 6 decimales, en formato es-AR: "1234.5" → "1.234,500000". */
export function formatPuntos(value: string): string {
  return formatDecimal(value, 6)
}
