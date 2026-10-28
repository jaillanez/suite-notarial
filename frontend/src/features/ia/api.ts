import { api } from '../../lib/api'
import type { Acto, ActoInput } from '../ddjj/api'
import type { EscribanoDetalle, EscribanoInput } from '../padron/api'

const P = '/v1/ia'

export type TipoSugerencia = 'EXTRACCION_MINUTA' | 'OCR_DNI' | 'EXTRACCION_INDICE'
export type EstadoSugerencia = 'SUGERIDO_POR_IA' | 'RATIFICADA' | 'DESCARTADA'
export type NivelAlerta = 'ADVERTENCIA' | 'AVISO'

/** Un dato propuesto por el motor, con la regla que lo produjo y el texto que lo respalda. */
export interface CampoSugerido {
  valor: string | null
  /** 0 a 1 con 4 decimales, como texto. */
  confianza: string
  regla: string
  evidencia: string | null
}

export interface AlertaIa {
  codigo: string
  nivel: NivelAlerta
  mensaje: string
  evidencia: string | null
}

export interface Sugerencia {
  id: string
  tipo: TipoSugerencia
  estado: EstadoSugerencia
  motor: string
  motor_version: string
  confianza: string
  tiempo_ms: number
  entrada: {
    origen: string
    mime_type: string | null
    caracteres: number | null
    paginas: number | null
    ocr: string | null
    /** Índice del protocolo: foto y renglón de esta sugerencia. */
    foto?: number | null
    renglon?: number | null
  }
  campos: Record<string, CampoSugerido>
  alertas: AlertaIa[]
  ddjj_id: string | null
  campos_modificados: string[] | null
  acto_id: string | null
  escribano_id: string | null
  resuelto_en: string | null
  created_at: string
}

export interface EstadoIa {
  ocr_disponible: boolean
  idiomas_ocr: string | null
  max_mb: number
}

// La lectura y el OCR pueden tardar: más margen que el resto de la API.
const LECTURA = { timeout: 120_000 }

export async function fetchEstadoIa(): Promise<EstadoIa> {
  return (await api.get<EstadoIa>(`${P}/estado`)).data
}

export async function analizarMinuta(
  ddjjId: string,
  entrada: { archivo: File } | { texto: string },
): Promise<Sugerencia> {
  const form = new FormData()
  form.append('ddjj_id', ddjjId)
  if ('archivo' in entrada) form.append('archivo', entrada.archivo)
  else form.append('texto', entrada.texto)
  return (await api.post<Sugerencia>(`${P}/minutas`, form, LECTURA)).data
}

export interface LecturaIndice {
  lote: string
  motor: string
  /** Una sugerencia de acto por renglón, en el orden del índice. */
  sugerencias: Sugerencia[]
}

export async function analizarIndice(ddjjId: string, fotos: File[]): Promise<LecturaIndice> {
  const form = new FormData()
  form.append('ddjj_id', ddjjId)
  for (const foto of fotos) form.append('archivos', foto)
  // Varias fotos leídas una tras otra: más margen todavía.
  return (await api.post<LecturaIndice>(`${P}/indices`, form, { timeout: 300_000 })).data
}

export async function analizarDni(archivo: File): Promise<Sugerencia> {
  const form = new FormData()
  form.append('archivo', archivo)
  return (await api.post<Sugerencia>(`${P}/dni`, form, LECTURA)).data
}

export async function ratificarActo(
  id: string,
  data: ActoInput,
): Promise<{ sugerencia: Sugerencia; acto: Acto }> {
  return (
    await api.post<{ sugerencia: Sugerencia; acto: Acto }>(
      `${P}/sugerencias/${id}/ratificar-acto`,
      data,
    )
  ).data
}

export async function ratificarEscribano(
  id: string,
  data: EscribanoInput,
): Promise<{ sugerencia: Sugerencia; escribano: EscribanoDetalle }> {
  return (
    await api.post<{ sugerencia: Sugerencia; escribano: EscribanoDetalle }>(
      `${P}/sugerencias/${id}/ratificar-escribano`,
      data,
    )
  ).data
}

export async function descartarSugerencia(id: string, motivo?: string): Promise<Sugerencia> {
  return (
    await api.post<Sugerencia>(`${P}/sugerencias/${id}/descartar`, { motivo: motivo ?? null })
  ).data
}
