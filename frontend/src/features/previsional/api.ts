import { api } from '../../lib/api'
import type { Page } from '../users/api'

/** Cómo quedó asociado un nombre de la planilla histórica a un escribano del padrón. */
export type Vinculacion = 'EXACTA' | 'HEREDADA' | 'MANUAL'
export type EstadoVinculo = 'SIN_VINCULAR' | 'APROXIMADA' | 'HEREDADA'

export interface EscribanoResumen {
  id: string
  apellido_nombre: string
  matricula_numero: number
  tipo_documento: string
  numero_documento: string
}

/** Importes con 2 decimales y puntos con 6, como texto decimal (nunca number). */
export interface FilaPuntos {
  anio: number
  fecha_inicio: string
  fecha_cierre: string
  aportes: string
  puntos: string
}

export interface InformePuntos {
  escribano: EscribanoResumen
  filas: FilaPuntos[]
  origenes: { nombre_origen: string; vinculacion: Vinculacion; ejercicios: number }[]
  total_aportes: string
  total_puntos: string
}

export interface SinVincular {
  nombre_origen: string
  estado: EstadoVinculo
  ejercicios: number
  primer_anio: number
  ultimo_anio: number
  total_aportes: string
  total_puntos: string
  escribano: EscribanoResumen | null
}

export interface EstadoCalculo {
  habilitado: boolean
  motivo: string
}

const P = '/v1/previsional'

export async function fetchPuntosEscribano(escribanoId: string): Promise<InformePuntos> {
  return (await api.get<InformePuntos>(`${P}/escribanos/${escribanoId}/puntos`)).data
}

export async function fetchMisPuntos(): Promise<InformePuntos> {
  return (await api.get<InformePuntos>(`${P}/mis-puntos`)).data
}

export async function fetchSinVincular(
  estado: EstadoVinculo,
  q: string,
  page: number,
  pageSize: number,
): Promise<Page<SinVincular>> {
  const params: Record<string, string | number> = { estado, page, page_size: pageSize }
  if (q.trim()) params.q = q.trim()
  return (await api.get<Page<SinVincular>>(`${P}/puntos/sin-vincular`, { params })).data
}

export async function vincular(data: {
  nombre_origen: string
  escribano_id: string
  motivo: string | null
}): Promise<{ filas: number }> {
  return (await api.post<{ filas: number }>(`${P}/puntos/vincular`, data)).data
}

/** Descarta la sugerencia aproximada de un nombre (sigue sin vincular). */
export async function rechazarSugerencia(data: {
  nombre_origen: string
  motivo: string
}): Promise<{ filas: number }> {
  return (await api.post<{ filas: number }>(`${P}/puntos/rechazar-sugerencia`, data)).data
}

export async function fetchEstadoCalculo(): Promise<EstadoCalculo> {
  return (await api.get<EstadoCalculo>(`${P}/calculo`)).data
}

/** Descarga el «Informe de aportes y puntos» (propio si no se indica escribano). */
export async function descargarInforme(escribano?: EscribanoResumen): Promise<void> {
  const url = escribano ? `${P}/escribanos/${escribano.id}/puntos/pdf` : `${P}/mis-puntos/pdf`
  const response = await api.get<Blob>(url, { responseType: 'blob', timeout: 60_000 })
  const disposition = String(response.headers['content-disposition'] ?? '')
  const nombre = /filename="([^"]+)"/.exec(disposition)?.[1] ?? 'informe-aportes-puntos.pdf'
  const href = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = href
  link.download = nombre
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(href)
}
