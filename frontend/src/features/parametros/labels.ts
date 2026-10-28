import type { Tone } from '../../components/StatusIndicator'
import { formatMoney, formatPercent } from '../../lib/decimal'
import type { EstadoVigencia, PeriodoTasa, ReglaRedondeo, TipoConcepto, Vigencia } from './api'

export const TIPO: Record<TipoConcepto, { label: string; ayuda: string }> = {
  PORCENTUAL_ACTO: {
    label: 'Porcentaje sobre escrituras',
    ayuda: 'Porcentaje sobre la base imponible de cada acto, con mínimo y tope opcionales.',
  },
  FIJO_ACTO: { label: 'Monto fijo por acto', ayuda: 'Importe fijo por cada acto.' },
  FIJO_MENSUAL: { label: 'Monto fijo mensual', ayuda: 'Importe fijo por período mensual.' },
  TASA_MORA: {
    label: 'Tasa de mora',
    ayuda: 'Interés por pago fuera de término (tasa mensual o anual), con días de gracia.',
  },
}

export const ESTADO_VIGENCIA: Record<EstadoVigencia, { label: string; tone: Tone }> = {
  PENDIENTE_APROBACION: { label: 'Pendiente de aprobación', tone: 'warning' },
  VIGENTE: { label: 'Aprobada', tone: 'success' },
  RECHAZADA: { label: 'Rechazada', tone: 'danger' },
  RETIRADA: { label: 'Retirada', tone: 'unknown' },
}

export const PERIODO_TASA: Record<PeriodoTasa, string> = { MENSUAL: 'mensual', ANUAL: 'anual' }

export const REDONDEO: Record<ReglaRedondeo, string> = {
  HALF_UP: 'Al más cercano (0,5 hacia arriba)',
  FLOOR: 'Hacia abajo',
  CEILING: 'Hacia arriba',
}

/** Valor principal de una vigencia, en una línea legible. */
export function resumenValor(tipo: TipoConcepto, v: Vigencia): string {
  if (tipo === 'PORCENTUAL_ACTO') return formatPercent(v.porcentaje)
  if (tipo === 'FIJO_ACTO') return `${formatMoney(v.monto_fijo)} por acto`
  if (tipo === 'FIJO_MENSUAL') return formatMoney(v.monto_fijo)
  return `${formatPercent(v.tasa)} ${v.periodo_tasa ? PERIODO_TASA[v.periodo_tasa] : ''}`.trim()
}

/** Valores secundarios (mínimo, tope, gracia) como pares etiqueta/valor. */
export function detalleValores(tipo: TipoConcepto, v: Vigencia): [string, string][] {
  if (tipo === 'PORCENTUAL_ACTO') {
    return [
      ['Porcentaje', formatPercent(v.porcentaje)],
      ['Mínimo', v.monto_minimo ? formatMoney(v.monto_minimo) : 'Sin mínimo'],
      ['Tope', v.monto_maximo ? formatMoney(v.monto_maximo) : 'Sin tope'],
      ['Redondeo', REDONDEO[v.regla_redondeo]],
    ]
  }
  if (tipo === 'FIJO_ACTO' || tipo === 'FIJO_MENSUAL') {
    return [
      ['Monto', formatMoney(v.monto_fijo)],
      ['Redondeo', REDONDEO[v.regla_redondeo]],
    ]
  }
  return [
    ['Tasa', formatPercent(v.tasa)],
    ['Unidad', v.periodo_tasa ? PERIODO_TASA[v.periodo_tasa] : '—'],
    ['Días de gracia', String(v.dias_gracia ?? 0)],
    ['Redondeo', REDONDEO[v.regla_redondeo]],
  ]
}
