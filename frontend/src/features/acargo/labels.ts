import type { Tone } from '../../components/StatusIndicator'
import type { Designacion } from './api'

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
