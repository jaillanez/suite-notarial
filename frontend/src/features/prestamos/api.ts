import { api } from '../../lib/api'

export type Sistema = 'FRANCES' | 'ALEMAN'
export type EstadoPrestamo = 'SOLICITADO' | 'OTORGADO' | 'RECHAZADO' | 'CANCELADO'
export type EstadoCuota = 'PENDIENTE' | 'PAGADA'
/** Moneda de la línea y de sus préstamos: capital, cuotas e ingreso van en la misma. */
export type Moneda = 'ARS' | 'USD'

/** Importes y tasas como texto decimal ("8884.88", "30.0000"), nunca como number. */
export interface Linea {
  id: string
  codigo: string
  nombre: string
  descripcion: string | null
  sistema: Sistema
  plazo_minimo: number
  plazo_maximo: number
  monto_minimo: string
  monto_maximo: string
  tna: string
  afectacion_maxima: string
  requiere_garante: boolean
  moneda: Moneda
  garantia: string | null
  requisito_conducta: string | null
  /** Capital sobre el valor del inmueble hipotecado, en % ("70.0000"). */
  relacion_capital_hipoteca: string | null
  requiere_certificado_ingresos: boolean
  requiere_certificado_bienes: boolean
  antiguedad_minima_meses: number | null
  es_ejemplo: boolean
  is_active: boolean
}

export type LineaInput = Omit<Linea, 'id'>

export interface Cuota {
  numero: number
  vencimiento: string
  saldo_inicial: string
  amortizacion: string
  interes: string
  cuota: string
  saldo_final: string
  estado: EstadoCuota
  vencida: boolean
  fecha_pago: string | null
  importe_pagado: string | null
}

export interface Totales {
  capital: string
  intereses: string
  total: string
}

export interface Evaluacion {
  moneda: Moneda
  sistema: Sistema
  tna: string
  tasa_es_ejemplo: boolean
  capital: string
  cuotas: number
  cuota_maxima: string
  otras_cuotas: string
  afectacion: string | null
  afectacion_maxima: string
  requiere_garante: boolean
  impedimentos: string[]
  /** No impiden otorgar, pero hay que revisarlos (tipo de cambio, antigüedad). */
  avisos: string[]
  plan: Cuota[]
  totales: Totales
}

export interface PersonaResumen {
  id: string
  apellido_nombre: string
  matricula_numero: number
}

export interface Prestamo {
  id: string
  numero: number
  escribano: PersonaResumen
  garante: PersonaResumen | null
  linea_id: string
  linea_nombre: string
  estado: EstadoPrestamo
  moneda: Moneda
  sistema: Sistema
  tna: string
  tasa_es_ejemplo: boolean
  capital: string
  cuotas: number
  /** null cuando quien mira es solo el garante: no ve la situación del titular. */
  ingreso_neto: string | null
  otras_cuotas: string | null
  cuota_maxima: string
  afectacion: string | null
  afectacion_maxima: string
  observaciones: string | null
  motivo_rechazo: string | null
  fecha_otorgamiento: string | null
  creado_por: string | null
  resuelto_por: string | null
  resuelto_en: string | null
  created_at: string
  saldo_capital: string | null
  cuotas_pagadas: number
  cuotas_vencidas: number
}

export interface PrestamoDetalle extends Prestamo {
  plan: Cuota[]
  totales: Totales
  impedimentos_actuales: string[]
  avisos_actuales: string[]
  puede_resolver: boolean
}

export interface SimulacionInput {
  linea_id: string
  capital: string
  cuotas: number
  ingreso_neto: string | null
  escribano_id?: string | null
  garante_escribano_id?: string | null
}

const P = '/v1/prestamos'

export async function fetchLineas(): Promise<Linea[]> {
  return (await api.get<Linea[]>(`${P}/lineas`)).data
}

export async function guardarLinea(data: LineaInput, id?: string): Promise<Linea> {
  return id
    ? (await api.put<Linea>(`${P}/lineas/${id}`, data)).data
    : (await api.post<Linea>(`${P}/lineas`, data)).data
}

export async function simular(data: SimulacionInput): Promise<Evaluacion> {
  return (await api.post<Evaluacion>(`${P}/simular`, data)).data
}

export async function fetchPrestamos(estado: EstadoPrestamo | ''): Promise<Prestamo[]> {
  return (await api.get<Prestamo[]>(P, { params: { estado: estado || undefined } })).data
}

export async function fetchPrestamo(id: string): Promise<PrestamoDetalle> {
  return (await api.get<PrestamoDetalle>(`${P}/${id}`)).data
}

export async function crearSolicitud(data: {
  escribano_id: string
  linea_id: string
  capital: string
  cuotas: number
  ingreso_neto: string
  garante_escribano_id: string | null
  observaciones: string | null
}): Promise<PrestamoDetalle> {
  return (await api.post<PrestamoDetalle>(P, data)).data
}

export async function otorgar(id: string): Promise<PrestamoDetalle> {
  return (await api.post<PrestamoDetalle>(`${P}/${id}/otorgar`)).data
}

export async function rechazar(id: string, motivo: string): Promise<PrestamoDetalle> {
  return (await api.post<PrestamoDetalle>(`${P}/${id}/rechazar`, { motivo })).data
}

export async function registrarPago(
  id: string,
  numero: number,
  data: { fecha_pago: string; importe: string },
): Promise<PrestamoDetalle> {
  return (await api.post<PrestamoDetalle>(`${P}/${id}/cuotas/${String(numero)}/pago`, data)).data
}
