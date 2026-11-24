import type { Tone } from '../../components/StatusIndicator'
import { compararDecimal, formatImporte, formatPercent } from '../../lib/decimal'
import type { Cuota, EstadoPrestamo, Linea, Moneda, Sistema, TipoDocumento } from './api'

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

/** Leyenda de las líneas en dólares (criterio de la Caja, 20/11 y 23/11/2026). */
export const LEYENDA_USD =
  'Línea en dólares: los ingresos mínimos informados están expresados en dólares, y los ingresos se declaran en dólares al tipo de cambio comprador del Banco de la Nación Argentina.'

/** Capital tipeado: nunca más que el máximo de la línea (pedido de la Caja, 23/11/2026). Lo
 * que no es un número se deja como está: lo marca el error del campo. */
export function topeCapital(l: Linea | undefined, valor: string): string {
  if (l && /^\d+(\.\d{0,2})?$/.test(valor) && compararDecimal(valor, l.monto_maximo) > 0) {
    return l.monto_maximo
  }
  return valor
}

/** Cuotas tipeadas: solo dígitos, y nunca más que el plazo máximo de la línea. */
export function topeCuotas(l: Linea | undefined, valor: string): string {
  const limpio = valor.replace(/\D/g, '')
  if (l && limpio && Number(limpio) > l.plazo_maximo) return String(l.plazo_maximo)
  return limpio
}

/** Documentos que la línea exige para otorgar (igual que service.documentacion_requerida). */
export function documentosDeLinea(l: Linea): TipoDocumento[] {
  const r: TipoDocumento[] = []
  if (l.requiere_certificado_ingresos) r.push('CERTIFICADO_INGRESOS')
  if (l.requiere_certificado_bienes) r.push('CERTIFICADO_BIENES')
  return r
}

/** Capital y cuotas fuera de lo que admite la línea: el error de cada campo (o undefined). */
export function fueraDeLinea(
  l: Linea | undefined,
  capital: string,
  cuotas: number,
): { capital?: string; cuotas?: string } {
  if (!l) return {}
  const errores: { capital?: string; cuotas?: string } = {}
  if (/^\d+(\.\d{1,2})?$/.test(capital)) {
    if (compararDecimal(capital, l.monto_maximo) > 0) {
      errores.capital = `El máximo de la línea es ${importe(l.monto_maximo, l.moneda)}.`
    } else if (compararDecimal(capital, l.monto_minimo) < 0) {
      errores.capital = `El mínimo de la línea es ${importe(l.monto_minimo, l.moneda)}.`
    }
  }
  if (Number.isFinite(cuotas) && cuotas > 0) {
    if (cuotas > l.plazo_maximo) errores.cuotas = `Hasta ${String(l.plazo_maximo)} cuotas.`
    else if (cuotas < l.plazo_minimo) errores.cuotas = `Desde ${String(l.plazo_minimo)} cuotas.`
  }
  return errores
}

export function estadoCuota(c: Cuota): { label: string; tone: Tone } {
  if (c.estado === 'PAGADA') return { label: 'Pagada', tone: 'success' }
  if (c.vencida) return { label: 'Vencida', tone: 'danger' }
  return { label: 'A vencer', tone: 'unknown' }
}

/** Igual que en el servidor (catalog.NOMBRE_DOCUMENTO). */
export const TIPO_DOCUMENTO: Record<TipoDocumento, string> = {
  DOCUMENTO_IDENTIDAD: 'Documento de identidad',
  CERTIFICADO_INGRESOS: 'Certificado de ingresos',
  CERTIFICADO_BIENES: 'Certificado de bienes y deudas',
  GARANTIA: 'Documentación de la garantía',
  OTRO: 'Otro documento',
}
