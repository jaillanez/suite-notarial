import type { Tone } from '../../components/StatusIndicator'
import { formatImporte, formatPercent } from '../../lib/decimal'
import type { Cuota, EstadoPrestamo, Linea, Moneda, Sistema } from './api'

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

/** Símbolo y nombre de cada moneda: los importes de un préstamo van todos en la suya. */
export const MONEDA: Record<Moneda, { simbolo: string; label: string; en: string }> = {
  ARS: { simbolo: '$', label: 'Pesos', en: 'en pesos' },
  USD: { simbolo: 'US$', label: 'Dólares estadounidenses', en: 'en dólares' },
}

/** Importe con el símbolo de su moneda: "$ 1.500,00" o "US$ 1.500,00". */
export function importe(value: string | null, moneda: Moneda): string {
  return formatImporte(value, MONEDA[moneda].simbolo)
}

/** 12 → "1 año"; 18 → "18 meses". */
export function textoMeses(meses: number): string {
  if (meses % 12 === 0) {
    const anios = meses / 12
    return anios === 1 ? '1 año' : `${String(anios)} años`
  }
  return meses === 1 ? '1 mes' : `${String(meses)} meses`
}

/** Requisitos de la línea en frases cortas, para el personal y para el escribano. */
export function requisitosLinea(l: Linea): string[] {
  const r: string[] = []
  if (l.garantia) r.push(`Garantía: ${l.garantia.replace(/\.$/, '')}`)
  if (l.relacion_capital_hipoteca !== null) {
    r.push(
      `Capital hasta el ${formatPercent(l.relacion_capital_hipoteca)} del valor del inmueble hipotecado`,
    )
  }
  if (l.requiere_garante) r.push('Garante solidario matriculado')
  if (l.requiere_certificado_ingresos) r.push('Certificado de ingresos')
  if (l.requiere_certificado_bienes) r.push('Certificado de bienes y deudas')
  if (l.antiguedad_minima_meses !== null) {
    r.push(`Antigüedad en la matrícula: ${textoMeses(l.antiguedad_minima_meses)}`)
  }
  if (l.requisito_conducta) r.push(l.requisito_conducta.replace(/\.$/, ''))
  return r
}

export function estadoCuota(c: Cuota): { label: string; tone: Tone } {
  if (c.estado === 'PAGADA') return { label: 'Pagada', tone: 'success' }
  if (c.vencida) return { label: 'Vencida', tone: 'danger' }
  return { label: 'Pendiente', tone: 'unknown' }
}
