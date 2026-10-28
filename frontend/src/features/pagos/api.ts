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
  origen: OrigenComprobante
  /** Vacíos en un comprobante de Mercado Pago (no tiene archivo). */
  nombre_original: string | null
  mime_type: string | null
  tamano_bytes: number | null
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
  /** Solo en un comprobante de Mercado Pago. */
  mercado_pago: PagoMercadoPago | null
}

export type OrigenComprobante = 'ARCHIVO' | 'MERCADO_PAGO'

export type EstadoPagoMP =
  | 'CREADO'
  | 'pending'
  | 'authorized'
  | 'in_process'
  | 'in_mediation'
  | 'approved'
  | 'rejected'
  | 'cancelled'
  | 'refunded'
  | 'charged_back'

/** Lo que informó Mercado Pago (la Suite lo consulta a su API). Importes como texto. */
export interface PagoMercadoPago {
  id: string
  boleta_id: string
  estado: EstadoPagoMP
  estado_detalle: string | null
  mp_payment_id: string | null
  medio_pago: string | null
  importe_boleta: string
  importe_pagado: string | null
  comision: string | null
  importe_neto: string | null
  aprobado_en: string | null
  comprobante_id: string | null
  created_at: string
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

// --------------------------------------------------------------------------- Mercado Pago

export async function fetchMercadoPagoHabilitado(): Promise<boolean> {
  return (await api.get<{ habilitado: boolean }>(`${P}/mercadopago/estado`)).data.habilitado
}

/** Arma el cobro en Mercado Pago y devuelve la dirección a la que hay que ir a pagar. */
export async function pagarConMercadoPago(boletaId: string): Promise<string> {
  return (await api.post<{ url_pago: string }>(`${P}/boletas/${boletaId}/mercadopago`)).data
    .url_pago
}

/** Al volver de Mercado Pago: la Suite consulta el pago y lo registra. */
export async function sincronizarPagoMP(pagoId: string): Promise<PagoMercadoPago> {
  return (await api.post<PagoMercadoPago>(`${P}/mercadopago/${pagoId}/sincronizar`)).data
}

export async function fetchRegistroMP(page: number): Promise<Page<PagoMercadoPago>> {
  return (
    await api.get<Page<PagoMercadoPago>>(`${P}/mercadopago`, { params: { page, page_size: 25 } })
  ).data
}
