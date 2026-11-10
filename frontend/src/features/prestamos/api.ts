import { api } from '../../lib/api'
import type { EstadoPagoMP } from '../pagos/api'

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
  matricula_numero: number | null
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

/** Pago de una cuota con Mercado Pago, tal como lo informó Mercado Pago. */
export interface CobroCuotaMP {
  id: string
  cuota: number
  estado: EstadoPagoMP
  medio_pago: string | null
  importe_pagado: string | null
  aprobado_en: string | null
  confirmado_en: string | null
  /** Aprobado por Mercado Pago y todavía sin confirmar por Tesorería. */
  a_confirmar: boolean
}

export type TipoDocumento =
  'DOCUMENTO_IDENTIDAD' | 'CERTIFICADO_INGRESOS' | 'CERTIFICADO_BIENES' | 'GARANTIA' | 'OTRO'

/** Documento de la solicitud. Anulado sigue a la vista, pero ya no cuenta. */
export interface DocumentoPrestamo {
  id: string
  tipo: TipoDocumento
  descripcion: string | null
  nombre_original: string
  mime_type: string
  tamano_bytes: number
  subido_por: string
  created_at: string
  anulado_en: string | null
  motivo_anulacion: string | null
  puede_anular: boolean
}

/** Documento que exige la línea y si ya hay uno vigente cargado. */
export interface Requisito {
  tipo: TipoDocumento
  cargado: boolean
}

export interface SaldoMoneda {
  moneda: Moneda
  prestamos_vigentes: number
  saldo_capital: string
  cuotas_pendientes: number
  /** Capital más intereses de las cuotas que faltan pagar. */
  total_pendiente: string
  cuotas_vencidas: number
  importe_vencido: string
  proximo_vencimiento: string | null
  importe_proximo_vencimiento: string
}

/** Préstamos vigentes de un escribano como titular (o de toda la cartera), por moneda. */
export interface SaldoConjunto {
  escribano: PersonaResumen | null
  monedas: SaldoMoneda[]
  solicitudes_pendientes: number
}

export interface PrestamoDetalle extends Prestamo {
  plan: Cuota[]
  totales: Totales
  impedimentos_actuales: string[]
  avisos_actuales: string[]
  puede_resolver: boolean
  /** Pagos con Mercado Pago informados, los últimos primero. */
  cobros_mp: CobroCuotaMP[]
  /** Quien mira tomó el préstamo y puede pagar la próxima cuota con Mercado Pago. */
  puede_pagar_mp: boolean
  /** Vacíos para el garante: no ve la documentación del titular. */
  documentos: DocumentoPrestamo[]
  documentacion_requerida: Requisito[]
  puede_cargar_documentos: boolean
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

/** Arma el cobro de la próxima cuota y devuelve la dirección de Mercado Pago. */
export async function pagarCuotaConMercadoPago(id: string): Promise<string> {
  return (await api.post<{ url_pago: string }>(`${P}/${id}/mercadopago`)).data.url_pago
}

export async function confirmarCobroMP(id: string, pagoId: string): Promise<PrestamoDetalle> {
  return (
    await api.post<PrestamoDetalle>(
      `${P}/${id}/mercadopago/${encodeURIComponent(pagoId)}/confirmar`,
    )
  ).data
}

export async function fetchSaldo(escribanoId?: string): Promise<SaldoConjunto> {
  return (await api.get<SaldoConjunto>(`${P}/saldo`, { params: { escribano_id: escribanoId } }))
    .data
}

export async function cargarDocumento(
  id: string,
  data: { tipo: TipoDocumento; descripcion: string; archivo: File },
): Promise<PrestamoDetalle> {
  const form = new FormData()
  form.append('tipo', data.tipo)
  if (data.descripcion) form.append('descripcion', data.descripcion)
  form.append('archivo', data.archivo)
  return (await api.post<PrestamoDetalle>(`${P}/${id}/documentos`, form, { timeout: 120_000 })).data
}

export async function anularDocumento(
  id: string,
  documentoId: string,
  motivo: string,
): Promise<PrestamoDetalle> {
  return (
    await api.post<PrestamoDetalle>(`${P}/${id}/documentos/${documentoId}/anular`, { motivo })
  ).data
}

/** Descarga el archivo por el cliente HTTP (renueva la sesión si venció) y lo guarda. */
export async function descargarDocumento(
  id: string,
  doc: DocumentoPrestamo,
  nombre: string,
): Promise<void> {
  const response = await api.get<Blob>(`${P}/${id}/documentos/${doc.id}/archivo`, {
    responseType: 'blob',
    timeout: 60_000,
  })
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = nombre
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
