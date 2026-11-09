import type { Tone } from '../../components/StatusIndicator'
import type { AporteACargo, Designacion } from './api'

/** Qué paga quien está a cargo por los actos del registro (cada escribano tiene su boleta). */
export const APORTE_A_CARGO: Record<AporteACargo, { titulo: string; detalle: string }> = {
  SOLO_ACTOS: {
    titulo: 'Solo sus actos',
    detalle:
      'Boleta propia con el aporte de los actos que autoriza. El mínimo y el aporte médico los paga en su registro.',
  },
  CON_MINIMO: {
    titulo: 'Con mínimo',
    detalle:
      'Boleta propia con el mínimo mensual y el excedente sobre sus actos, sin aporte médico.',
  },
  EN_BOLETA_DEL_TITULAR: {
    titulo: 'En la boleta del titular',
    detalle: 'No tiene boleta propia: sus actos se cobran en la boleta del titular del registro.',
  },
}

/** Estado tal como lo lee la escribanía: no solo si se aprobó, sino si rige hoy. */
export function situacion(d: Designacion, hoy: string): { tone: Tone; label: string } {
  if (d.estado === 'PENDIENTE') return { tone: 'warning', label: 'Espera aprobación' }
  if (d.estado === 'RECHAZADA') return { tone: 'danger', label: 'Rechazada' }
  if (d.estado === 'ANULADA') return { tone: 'unknown', label: 'Anulada' }
  if (d.rige_hoy) return { tone: 'success', label: 'A cargo hoy' }
  return d.fecha_desde > hoy
    ? { tone: 'unknown', label: 'Programada' }
    : { tone: 'unknown', label: 'Cumplida' }
}
