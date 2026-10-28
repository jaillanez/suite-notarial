import type { Tone } from '../../components/StatusIndicator'
import type { EstadoComprobante, EstadoPagoMP } from './api'

export const ESTADO_COMPROBANTE: Record<
  EstadoComprobante,
  { label: string; tone: Tone; ayuda: string }
> = {
  PENDIENTE_REVISION: {
    label: 'En revisión',
    tone: 'warning',
    ayuda: 'Tesorería tiene que confirmar el pago contra el extracto bancario.',
  },
  APROBADO: { label: 'Pago confirmado', tone: 'success', ayuda: 'Tesorería confirmó el pago.' },
  RECHAZADO: {
    label: 'Rechazado',
    tone: 'danger',
    ayuda: 'Tesorería no pudo confirmar el pago.',
  },
}

/** Motivos frecuentes de rechazo: completan el campo, que se puede editar. */
export const MOTIVOS_FRECUENTES = [
  'El importe transferido no coincide con el total de la boleta.',
  'La transferencia no figura en el extracto bancario.',
  'El comprobante es ilegible o está incompleto.',
  'La cuenta de destino no es la de la Caja.',
  'El comprobante corresponde a otra boleta.',
]

/** Tamaño legible: "1,4 MB", "820 KB". */
export function formatTamano(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    const mb = Math.round((bytes / (1024 * 1024)) * 10) / 10
    return `${String(mb).replace('.', ',')} MB`
  }
  return `${String(Math.max(1, Math.round(bytes / 1024)))} KB`
}

/** Máximo que acepta el servidor (MAX_UPLOAD_MB). */
export const MAX_BYTES = 10 * 1024 * 1024
export const TIPOS_ACEPTADOS = 'application/pdf,image/png,image/jpeg'

/** Estado del pago tal como lo informa Mercado Pago, en palabras. */
export const ESTADO_PAGO_MP: Record<EstadoPagoMP, string> = {
  CREADO: 'Cobro armado, sin pago',
  pending: 'Pendiente',
  authorized: 'Autorizado',
  in_process: 'En proceso',
  in_mediation: 'En mediación',
  approved: 'Aprobado',
  rejected: 'Rechazado',
  cancelled: 'Cancelado',
  refunded: 'Devuelto',
  charged_back: 'Desconocido por el titular (contracargo)',
}
