import { formatLocalDateTime } from '../../lib/datetime'
import { formatMoney } from '../../lib/decimal'
import { formatPeriodo } from '../ddjj/labels'
import { formatDate } from '../padron/labels'
import type { Columna, Valor } from './api'

/** Códigos de estado ("PENDIENTE_REVISION") en palabras ("Pendiente revisión"). */
function humanizar(valor: string): string {
  if (!/^[A-Z][A-Z_]+$/.test(valor)) return valor
  const texto = valor.replace(/_/g, ' ').toLowerCase()
  return texto.charAt(0).toUpperCase() + texto.slice(1)
}

export function formatCelda(col: Columna, valor: Valor): string {
  if (valor === null || valor === '') return '—'
  switch (col.tipo) {
    case 'MONEDA':
      return formatMoney(String(valor))
    case 'FECHA':
      return formatDate(String(valor))
    case 'FECHA_HORA':
      return formatLocalDateTime(new Date(String(valor)))
    case 'PERIODO':
      return formatPeriodo(String(valor))
    case 'CUIT': {
      const d = String(valor)
      return d.length === 11 ? `${d.slice(0, 2)}-${d.slice(2, 10)}-${d.slice(10)}` : d
    }
    case 'ENTERO':
      return String(valor)
    default:
      return humanizar(String(valor))
  }
}

export function alineadaDerecha(col: Columna): boolean {
  return col.tipo === 'MONEDA' || (col.tipo === 'ENTERO' && col.total)
}
