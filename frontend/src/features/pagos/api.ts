import { api } from '../../lib/api'
import type { RegistroResumen } from '../ddjj/api'

export type EstadoComprobante = 'PENDIENTE_REVISION' | 'APROBADO' | 'RECHAZADO'

/** Importes como texto decimal ("594000.00"), nunca como number. */
export interface Comprobante {
  id: string
  boleta: {
    id: string
    numero: number
    ddjj_id: string
    registro: RegistroResumen
    periodo: string
    estado: string
    fecha_pago: string
    total_a_pagar: string
  }
  nombre_original: string
  mime_type: string
  tamano_bytes: number
  fecha_transferencia: string
  banco_origen: string | null
  numero_operacion: string
  importe_declarado: string
  diferencia: string
  estado: EstadoComprobante
  motivo_rechazo: string | null
  subido_por: string | null
  created_at: string
  revisado_en: string | null
  conciliacion: {
    resultado: 'APROBADO' | 'RECHAZADO'
    importe_confirmado: string | null
    fecha_acreditacion: string | null
    identificador_extracto: string | null
    observaciones: string | null
    operador: string | null
    created_at: string
  } | null
}

interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

const P = '/v1/pagos'

export async function adjuntarComprobante(
  boletaId: string,
  data: {
    archivo: File
    fecha_transferencia: string
    numero_operacion: string
    importe_declarado: string
    banco_origen: string
  },
): Promise<Comprobante> {
  const form = new FormData()
  form.append('archivo', data.archivo)
  form.append('fecha_transferencia', data.fecha_transferencia)
  form.append('numero_operacion', data.numero_operacion)
  form.append('importe_declarado', data.importe_declarado)
  if (data.banco_origen) form.append('banco_origen', data.banco_origen)
  return (
    await api.post<Comprobante>(`${P}/boletas/${boletaId}/comprobantes`, form, {
      timeout: 120_000,
    })
  ).data
}

export async function fetchMesa(params: {
  page: number
  pageSize: number
  estado: EstadoComprobante
}): Promise<Page<Comprobante>> {
  return (
    await api.get<Page<Comprobante>>(`${P}/comprobantes`, {
      params: { page: params.page, page_size: params.pageSize, estado: params.estado },
    })
  ).data
}

export async function fetchComprobante(id: string): Promise<Comprobante> {
  return (await api.get<Comprobante>(`${P}/comprobantes/${id}`)).data
}

/** El archivo llega por el cliente HTTP (renueva la sesión) como Blob para el visor. */
export async function fetchArchivo(id: string): Promise<Blob> {
  return (
    await api.get<Blob>(`${P}/comprobantes/${id}/archivo`, {
      responseType: 'blob',
      timeout: 60_000,
    })
  ).data
}

export async function aprobarComprobante(
  id: string,
  data: {
    importe_confirmado: string
    fecha_acreditacion: string
    identificador_extracto: string | null
    observaciones: string | null
  },
): Promise<Comprobante> {
  return (await api.post<Comprobante>(`${P}/comprobantes/${id}/aprobar`, data)).data
}

export async function rechazarComprobante(id: string, motivo: string): Promise<Comprobante> {
  return (await api.post<Comprobante>(`${P}/comprobantes/${id}/rechazar`, { motivo })).data
}
