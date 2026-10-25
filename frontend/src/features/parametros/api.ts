import { api } from '../../lib/api'

export type TipoConcepto = 'PORCENTUAL_ACTO' | 'FIJO_ACTO' | 'FIJO_MENSUAL' | 'TASA_MORA'
export type PeriodoTasa = 'MENSUAL' | 'ANUAL'
export type EstadoVigencia = 'PENDIENTE_APROBACION' | 'VIGENTE' | 'RECHAZADA'
export type ReglaRedondeo = 'HALF_UP' | 'FLOOR' | 'CEILING'

/** Los valores numéricos viajan como texto decimal ("1.5000"), nunca como number. */
export interface Vigencia {
  id: string
  concepto_id: string
  concepto_codigo: string
  version: number
  fecha_desde: string
  fecha_hasta: string | null
  porcentaje: string | null
  monto_fijo: string | null
  monto_minimo: string | null
  monto_maximo: string | null
  tasa: string | null
  periodo_tasa: PeriodoTasa | null
  dias_gracia: number | null
  regla_redondeo: ReglaRedondeo
  es_ejemplo: boolean
  estado: EstadoVigencia
  resolucion_respaldo: string
  motivo: string
  created_at: string
  creado_por: string | null
  aprobado_por: string | null
  fecha_aprobacion: string | null
  motivo_rechazo: string | null
}

export interface Concepto {
  id: string
  codigo: string
  nombre: string
  tipo: TipoConcepto
  descripcion: string | null
  is_active: boolean
  vigente: Vigencia | null
  pendientes: number
}

export interface VigenciaInput {
  fecha_desde: string
  fecha_hasta: string | null
  porcentaje?: string | null
  monto_fijo?: string | null
  monto_minimo?: string | null
  monto_maximo?: string | null
  tasa?: string | null
  periodo_tasa?: PeriodoTasa | null
  dias_gracia?: number | null
  regla_redondeo: ReglaRedondeo
  resolucion_respaldo: string
  motivo: string
}

export interface Simulacion {
  vigencia: Vigencia
  resultado: string
  dias_mora: number | null
  detalle: string
}

const P = '/v1/parametros'

export async function fetchConceptos(fecha: string): Promise<Concepto[]> {
  return (await api.get<Concepto[]>(`${P}/conceptos`, { params: { fecha } })).data
}

export async function createConcepto(data: {
  codigo: string
  nombre: string
  tipo: TipoConcepto
  descripcion: string | null
}): Promise<Concepto> {
  return (await api.post<Concepto>(`${P}/conceptos`, data)).data
}

export async function fetchVigencias(conceptoId: string): Promise<Vigencia[]> {
  return (await api.get<Vigencia[]>(`${P}/conceptos/${conceptoId}/vigencias`)).data
}

export async function proponerVigencia(conceptoId: string, data: VigenciaInput) {
  return (await api.post<Vigencia>(`${P}/conceptos/${conceptoId}/vigencias`, data)).data
}

export async function aprobarVigencia(id: string): Promise<Vigencia> {
  return (await api.post<Vigencia>(`${P}/vigencias/${id}/aprobar`)).data
}

export async function rechazarVigencia(id: string, motivo: string): Promise<Vigencia> {
  return (await api.post<Vigencia>(`${P}/vigencias/${id}/rechazar`, { motivo })).data
}

export async function simular(data: {
  concepto_codigo: string
  fecha: string
  base_imponible?: string
  monto?: string
  vencimiento?: string
  fecha_pago?: string
}): Promise<Simulacion> {
  return (await api.post<Simulacion>(`${P}/simulacion`, data)).data
}
