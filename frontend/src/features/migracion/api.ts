import { api } from '../../lib/api'

const P = '/v1/migracion'

export type ModoCorrida = 'SIMULACRO' | 'DEFINITIVA'
export type EstadoCorrida = 'EN_CURSO' | 'SIMULADA' | 'CARGADA' | 'FALLIDA'
export type Area = 'TESORERIA' | 'CAJA'
export type Severidad = 'BLOQUEANTE' | 'ADVERTENCIA'
export type Entidad = 'registros' | 'escribanos' | 'cargos' | 'boletas' | 'pagos'

export interface Conformidad {
  area: Area
  firmante: string
  firmada_en: string
  observaciones: string | null
}

export interface Corrida {
  id: string
  modo: ModoCorrida
  estado: EstadoCorrida
  huella_lote: string
  homologacion: string
  homologacion_ejemplo: boolean
  operador: string
  created_at: string
  finalizada_en: string | null
  duracion_ms: number | null
  cuadra: boolean | null
  bloqueantes: number | null
  advertencias: number | null
  conformidades: Conformidad[]
}

/** Importes como texto decimal ("1234.50"), nunca como number. */
export interface CuadraturaEntidad {
  entidad: Entidad
  control_filas: number
  leidas: number
  rechazadas: number
  cargadas: number
  cuadra_filas: boolean
  control_importe?: string | null
  control_importe_error?: string | null
  importe_leido?: string
  importe_rechazado?: string
  importe_cargado?: string | null
  filas_importe_ilegible?: number
  cuadra_importe?: boolean
}

export interface Informe {
  cuadra: boolean
  entidades: CuadraturaEntidad[]
  saldos: {
    registros: number
    deuda_total_origen: string
    deuda_total_destino: string
    diferencias: { registro: number; origen: string | null; destino: string | null }[]
  }
  boletas_por_estado: { estado: string; filas: number; importe: string }[]
  circunscripciones_nuevas: number
  bloqueantes: number
  advertencias: number
  observaciones_por_codigo: Record<string, number>
  codificaciones: Record<string, string>
}

export interface CorridaDetalle extends Corrida {
  informe: Informe | null
  error: string | null
  /** Tabla de homologación que cubren las conformidades: código del origen → valor en la Suite. */
  huella_homologacion: string
  homologacion_tablas: Record<string, Record<string, string>>
  pendiente_para_definitiva: string[]
}

export interface Observacion {
  entidad: Entidad
  fila: number
  codigo_legado: string
  codigo: string
  severidad: Severidad
  mensaje: string
}

export interface ObservacionesPage {
  items: Observacion[]
  total: number
  page: number
  page_size: number
}

export async function fetchCorridas(): Promise<Corrida[]> {
  return (await api.get<Corrida[]>(`${P}/corridas`)).data
}

export async function fetchCorrida(id: string): Promise<CorridaDetalle> {
  return (await api.get<CorridaDetalle>(`${P}/corridas/${id}`)).data
}

export async function fetchObservaciones(
  id: string,
  params: { page: number; pageSize: number; severidad: Severidad | ''; entidad: Entidad | '' },
): Promise<ObservacionesPage> {
  return (
    await api.get<ObservacionesPage>(`${P}/corridas/${id}/observaciones`, {
      params: {
        page: params.page,
        page_size: params.pageSize,
        severidad: params.severidad || undefined,
        entidad: params.entidad || undefined,
      },
    })
  ).data
}

export async function firmarConformidad(
  id: string,
  data: { area: Area; observaciones: string | null },
): Promise<CorridaDetalle> {
  return (await api.post<CorridaDetalle>(`${P}/corridas/${id}/conformidad`, data)).data
}
