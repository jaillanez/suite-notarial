import { api } from '../../lib/api'
import type { Cargo } from '../padron/api'
import type { EstadoComprobante } from '../pagos/api'
import type { PeriodoTasa } from '../parametros/api'

export type EstadoDDJJ = 'BORRADOR' | 'PRESENTADA' | 'RECTIFICADA'
export type EstadoBoleta = 'PENDIENTE' | 'PAGADA' | 'ANULADA'
export type CategoriaActo =
  'ESCRITURA_CON_VALOR' | 'ACTA_O_PODER' | 'OTRO_ACTO' | 'SIN_EFECTO' | 'EXENTO'
export type MotivoExencion = 'CONVENIO_IPV' | 'ACTA_SUBSANATORIA' | 'OTRO'
export type TipoProtocolo = 'GENERAL' | 'AUXILIAR'

export interface RegistroResumen {
  id: string
  numero_registro: number
  nombre_fantasia: string | null
  departamento: string
}

export interface EscribanoResumen {
  id: string
  apellido_nombre: string
  matricula_numero: number
  cargo: Cargo
}

export interface RegistroOperable extends RegistroResumen {
  escribanos: EscribanoResumen[]
}

/** Importes como texto decimal ("1081699.06"), nunca como number. */
export interface Acto {
  id: string
  escribano_id: string
  escribano: string
  matricula_numero: number
  cargo: Cargo
  tipo_protocolo: TipoProtocolo
  numero_escritura: number
  /** 1 para el primer acto de la escritura; 2, 3… para los demás (aporte múltiple). */
  orden_en_escritura: number
  folio: number | null
  fecha_acto: string
  naturaleza: string
  categoria: CategoriaActo
  base_imponible: string
  motivo_exencion: MotivoExencion | null
  detalle_exencion: string | null
  aporte: string | null
  vigencia_id: string | null
}

/** Días de atraso en que rigió una misma tasa (`desde` y `hasta` inclusive). */
export interface TramoMora {
  desde: string
  hasta: string
  dias: number
  tasa: string
  periodo_tasa: PeriodoTasa
  interes: string
}

export interface Boleta {
  id: string
  numero: number
  codigo_verificacion: string
  ddjj_id: string
  registro: RegistroResumen
  periodo: string
  numero_rectificativa: number
  estado: EstadoBoleta
  fecha_emision: string
  fecha_vencimiento: string
  fecha_pago: string
  dias_mora: number
  total_protocolos: string
  aporte_minimo: string
  excedente: string
  aporte_medico: string
  cantidad_aportes_medicos: number
  total_en_termino: string
  interes_mora: string
  /** Interés por tasa vigente en cada tramo de días de atraso (vacío en término). */
  tramos_mora: TramoMora[]
  total_a_pagar: string
  created_at: string
  emitida_por: string | null
  anulada_en: string | null
  motivo_anulacion: string | null
  /** Último comprobante adjuntado (adjuntar no es pagar: lo confirma Tesorería). */
  comprobante: {
    id: string
    /** ARCHIVO: lo adjuntó el escribano. MERCADO_PAGO: lo informó Mercado Pago. */
    origen: 'ARCHIVO' | 'MERCADO_PAGO'
    estado: EstadoComprobante
    importe_declarado: string
    motivo_rechazo: string | null
    created_at: string
  } | null
}

export interface Declaracion {
  id: string
  registro: RegistroResumen
  periodo: string
  numero_rectificativa: number
  estado: EstadoDDJJ
  observaciones: string | null
  fecha_presentacion: string | null
  presentada_por: string | null
  rectifica_a_id: string | null
  cantidad_actos: number
  total_protocolos: string | null
  vencimiento: string | null
  created_at: string
}

export type NivelControl = 'BLOQUEANTE' | 'ADVERTENCIA'

/** Control del libro de protocolo (numeración, folio o fecha). */
export interface ControlProtocolo {
  codigo: string
  nivel: NivelControl
  mensaje: string
}

/** Números de escritura salteados en el año, por protocolo. */
export interface Hueco {
  tipo_protocolo: TipoProtocolo
  /** Tramos consecutivos de números salteados. */
  tramos: { desde: number; hasta: number }[]
  total: number
}

export interface DeclaracionDetalle extends Declaracion {
  actos: Acto[]
  boletas: Boleta[]
  escribanos: EscribanoResumen[]
  puede_operar: boolean
  /** Solo los actos que tienen algún control, por id. */
  controles: Record<string, ControlProtocolo[]>
  huecos: Hueco[]
  /** Número de escritura que sigue en cada protocolo (la numeración es anual). */
  proximos_numeros: Record<TipoProtocolo, number>
}

export interface VerificacionActoInput {
  tipo_protocolo: TipoProtocolo
  numero_escritura: number | null
  folio: number | null
  fecha_acto: string | null
  categoria: CategoriaActo | null
  base_imponible: string | null
  acto_multiple: boolean
  excluir_acto_id?: string | null
}

export interface VerificacionActo {
  aporte: string | null
  controles: ControlProtocolo[]
}

export interface Liquidacion {
  aportes: { acto_id: string; aporte: string }[]
  vencimiento: string
  fecha_pago: string
  total_protocolos: string
  aporte_minimo: string
  excedente: string
  aporte_medico: string
  cantidad_aportes_medicos: number
  total_en_termino: string
  dias_mora: number
  interes_mora: string
  /** Interés por tasa vigente en cada tramo de días de atraso (vacío en término). */
  tramos_mora: TramoMora[]
  total_a_pagar: string
  usa_valores_de_ejemplo: boolean
}

export interface ActoInput {
  escribano_id: string
  tipo_protocolo: TipoProtocolo
  numero_escritura: number
  folio: number | null
  fecha_acto: string
  naturaleza: string
  categoria: CategoriaActo
  base_imponible: string
  acto_multiple: boolean
  motivo_exencion: MotivoExencion | null
  detalle_exencion: string | null
}

export interface Verificacion {
  numero: number
  codigo_verificacion: string
  registro_numero: number
  periodo: string
  estado: EstadoBoleta
  fecha_emision: string
  fecha_pago: string
  total_a_pagar: string
  integra: boolean
}

interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

const P = '/v1/ddjj'

export async function fetchRegistrosOperables(): Promise<RegistroOperable[]> {
  return (await api.get<RegistroOperable[]>(`${P}/registros`)).data
}

export async function fetchDeclaraciones(params: {
  page: number
  pageSize: number
  periodo: string
  estado: EstadoDDJJ | ''
}): Promise<Page<Declaracion>> {
  return (
    await api.get<Page<Declaracion>>(`${P}/declaraciones`, {
      params: {
        page: params.page,
        page_size: params.pageSize,
        periodo: params.periodo || undefined,
        estado: params.estado || undefined,
      },
    })
  ).data
}

export async function abrirDeclaracion(data: {
  registro_id: string
  periodo: string
}): Promise<DeclaracionDetalle> {
  return (await api.post<DeclaracionDetalle>(`${P}/declaraciones`, data)).data
}

export async function fetchDeclaracion(id: string): Promise<DeclaracionDetalle> {
  return (await api.get<DeclaracionDetalle>(`${P}/declaraciones/${id}`)).data
}

export async function fetchLiquidacion(id: string, fechaPago: string): Promise<Liquidacion> {
  return (
    await api.get<Liquidacion>(`${P}/declaraciones/${id}/liquidacion`, {
      params: { fecha_pago: fechaPago },
    })
  ).data
}

export async function agregarActo(id: string, data: ActoInput): Promise<Acto> {
  return (await api.post<Acto>(`${P}/declaraciones/${id}/actos`, data)).data
}

export async function verificarActo(
  id: string,
  data: VerificacionActoInput,
): Promise<VerificacionActo> {
  return (await api.post<VerificacionActo>(`${P}/declaraciones/${id}/actos/verificacion`, data))
    .data
}

export async function bajaActo(id: string, actoId: string, motivo: string): Promise<void> {
  await api.post(`${P}/declaraciones/${id}/actos/${actoId}/baja`, { motivo })
}

export async function presentar(
  id: string,
  data: { fecha_pago: string; observaciones: string | null },
): Promise<Boleta> {
  return (await api.post<Boleta>(`${P}/declaraciones/${id}/presentar`, data)).data
}

export async function emitirBoleta(id: string, fechaPago: string): Promise<Boleta> {
  return (await api.post<Boleta>(`${P}/declaraciones/${id}/boletas`, { fecha_pago: fechaPago }))
    .data
}

export async function rectificar(id: string): Promise<DeclaracionDetalle> {
  return (await api.post<DeclaracionDetalle>(`${P}/declaraciones/${id}/rectificar`)).data
}

/** Descarga el PDF por el cliente HTTP (renueva la sesión si venció) y lo guarda. */
export async function descargarBoleta(boleta: Boleta): Promise<void> {
  const response = await api.get<Blob>(`${P}/boletas/${boleta.id}/pdf`, {
    responseType: 'blob',
    timeout: 60_000,
  })
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = `boleta-${String(boleta.numero)}.pdf`
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export async function verificarBoleta(codigo: string): Promise<Verificacion> {
  return (await api.get<Verificacion>(`/v1/boletas/verificar/${encodeURIComponent(codigo)}`)).data
}

export async function fetchBoleta(id: string): Promise<Boleta> {
  return (await api.get<Boleta>(`/v1/ddjj/boletas/${id}`)).data
}
