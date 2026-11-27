import { api } from '../../lib/api'
import type { Comprobante } from '../pagos/api'

export type BoletaResumen = Comprobante['boleta']

export type TipoAjuste = 'CREDITO' | 'DEBITO'
export type ConceptoAjuste =
  'REDONDEO' | 'REDUCCION_INTERESES' | 'CONDONACION' | 'DIFERENCIA_RECTIFICATIVA' | 'OTRO'
export type EstadoAjuste = 'PROPUESTO' | 'APROBADO' | 'RECHAZADO'

/** Crédito o débito sobre una boleta (Caja, 26/11/2026). Los importes viajan como texto. */
export interface Ajuste {
  id: string
  boleta_id: string
  boleta_numero: number
  tipo: TipoAjuste
  concepto: ConceptoAjuste
  importe: string
  justificacion: string
  resolucion: string | null
  estado: EstadoAjuste
  propuesto_por: string | null
  propuesto_en: string
  resuelto_por: string | null
  resuelto_en: string | null
  motivo_rechazo: string | null
  /** Quien consulta tiene el permiso de aprobar y no lo propuso. */
  puede_resolver: boolean
}

export interface BoletaParaAjustar {
  boleta: BoletaResumen
  escribano: string | null
  ajustes: Ajuste[]
}

export interface AjusteInput {
  boleta_id: string
  tipo: TipoAjuste
  concepto: ConceptoAjuste
  importe: string
  justificacion: string
  resolucion: string | null
}

export interface PaginaAjustes {
  items: Ajuste[]
  total: number
  page: number
  page_size: number
}

const P = '/v1/ajustes'

export async function fetchAjustes(params: {
  estado: EstadoAjuste | ''
  page: number
  pageSize: number
}): Promise<PaginaAjustes> {
  return (
    await api.get<PaginaAjustes>(P, {
      params: {
        ...(params.estado ? { estado: params.estado } : {}),
        page: params.page,
        page_size: params.pageSize,
      },
    })
  ).data
}

export async function fetchBoletaParaAjustar(numero: number): Promise<BoletaParaAjustar> {
  return (await api.get<BoletaParaAjustar>(`${P}/boleta/${String(numero)}`)).data
}

export async function proponerAjuste(data: AjusteInput): Promise<Ajuste> {
  return (await api.post<Ajuste>(P, data)).data
}

export async function aprobarAjuste(id: string): Promise<Ajuste> {
  return (await api.post<Ajuste>(`${P}/${id}/aprobar`)).data
}

export async function rechazarAjuste(id: string, motivo: string): Promise<Ajuste> {
  return (await api.post<Ajuste>(`${P}/${id}/rechazar`, { motivo })).data
}
