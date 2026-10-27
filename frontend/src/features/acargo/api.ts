import { api } from '../../lib/api'
import type { Page } from '../users/api'

export type EstadoDesignacion = 'PENDIENTE' | 'APROBADA' | 'RECHAZADA' | 'ANULADA'

export interface Designacion {
  id: string
  registro_id: string
  numero_registro: number
  departamento: string
  escribano_id: string
  apellido_nombre: string
  matricula_numero: number
  fecha_desde: string
  fecha_hasta: string
  motivo: string
  estado: EstadoDesignacion
  rige_hoy: boolean
  created_at: string
  cargada_por: string | null
  resuelta_por: string | null
  resuelta_en: string | null
  motivo_resolucion: string | null
  puede_aprobar: boolean
  puede_anular: boolean
  puede_terminar: boolean
}

export interface DesignacionInput {
  registro_id: string
  escribano_id: string
  fecha_desde: string
  fecha_hasta: string
  motivo: string
}

export interface Ajustes {
  a_cargo_requiere_aprobacion: boolean
  updated_at: string | null
  puede_editar: boolean
}

export interface RegistroGestionable {
  id: string
  numero_registro: number
  departamento: string
}

export interface Elegible {
  id: string
  apellido_nombre: string
  matricula_numero: number
  numero_registro: number | null
  departamento: string | null
}

const BASE = '/v1/a-cargo'

export async function fetchDesignaciones(params: {
  page: number
  pageSize: number
  estado: EstadoDesignacion | ''
}): Promise<Page<Designacion>> {
  const { data } = await api.get<Page<Designacion>>(BASE, {
    params: {
      page: params.page,
      page_size: params.pageSize,
      estado: params.estado || undefined,
    },
  })
  return data
}

export async function fetchAjustes(): Promise<Ajustes> {
  const { data } = await api.get<Ajustes>(`${BASE}/ajustes`)
  return data
}

export async function fijarAjustes(requiere: boolean): Promise<Ajustes> {
  const { data } = await api.put<Ajustes>(`${BASE}/ajustes`, {
    a_cargo_requiere_aprobacion: requiere,
  })
  return data
}

export async function fetchRegistrosGestionables(): Promise<RegistroGestionable[]> {
  const { data } = await api.get<RegistroGestionable[]>(`${BASE}/registros`)
  return data
}

export async function buscarElegibles(q: string): Promise<Elegible[]> {
  const { data } = await api.get<Elegible[]>(`${BASE}/elegibles`, { params: { q } })
  return data
}

export async function designar(body: DesignacionInput): Promise<Designacion> {
  const { data } = await api.post<Designacion>(BASE, body)
  return data
}

export async function aprobar(id: string): Promise<Designacion> {
  const { data } = await api.post<Designacion>(`${BASE}/${id}/aprobar`)
  return data
}

export async function rechazar(id: string, motivo: string): Promise<Designacion> {
  const { data } = await api.post<Designacion>(`${BASE}/${id}/rechazar`, { motivo })
  return data
}

export async function anular(id: string, motivo: string): Promise<Designacion> {
  const { data } = await api.post<Designacion>(`${BASE}/${id}/anular`, { motivo })
  return data
}

export async function terminar(
  id: string,
  fechaHasta: string,
  motivo: string,
): Promise<Designacion> {
  const { data } = await api.post<Designacion>(`${BASE}/${id}/terminar`, {
    fecha_hasta: fechaHasta,
    motivo,
  })
  return data
}
