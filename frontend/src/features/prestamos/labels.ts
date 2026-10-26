import type { Tone } from '../../components/StatusIndicator'
import type { Cuota, EstadoPrestamo, Sistema } from './api'

export const ESTADO_PRESTAMO: Record<EstadoPrestamo, { label: string; tone: Tone }> = {
  SOLICITADO: { label: 'Solicitado', tone: 'warning' },
  OTORGADO: { label: 'Vigente', tone: 'success' },
  RECHAZADO: { label: 'Rechazado', tone: 'danger' },
  CANCELADO: { label: 'Cancelado', tone: 'unknown' },
}

export const SISTEMA: Record<Sistema, { label: string; ayuda: string }> = {
  FRANCES: {
    label: 'Sistema francés',
    ayuda: 'Cuota constante; el interés baja y el capital sube.',
  },
  ALEMAN: { label: 'Sistema alemán', ayuda: 'Capital constante; la cuota baja mes a mes.' },
}

export function estadoCuota(c: Cuota): { label: string; tone: Tone } {
  if (c.estado === 'PAGADA') return { label: 'Pagada', tone: 'success' }
  if (c.vencida) return { label: 'Vencida', tone: 'danger' }
  return { label: 'Pendiente', tone: 'unknown' }
}
