import type { Tone } from '../../components/StatusIndicator'
import type { EstadoPublicacion, TipoDocumento } from './api'

export const ESTADO_PUBLICACION: Record<EstadoPublicacion, { label: string; tone: Tone }> = {
  BORRADOR: { label: 'Borrador', tone: 'warning' },
  PUBLICADO: { label: 'Publicado', tone: 'success' },
  ARCHIVADO: { label: 'Archivado', tone: 'unknown' },
}

export const TIPO_DOCUMENTO: Record<TipoDocumento, string> = {
  ESTADO_CONTABLE: 'Estados contables',
  MEMORIA_ANUAL: 'Memoria anual',
  RESOLUCION: 'Resoluciones',
  OTRO: 'Otros documentos',
}

/** Fecha y hora larga en castellano, en hora de San Juan: "25 de octubre de 2026". */
export function fechaLarga(iso: string): string {
  return new Intl.DateTimeFormat('es-AR', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'America/Argentina/San_Juan',
  }).format(new Date(iso))
}

/** Párrafos de un texto plano (separados por una línea en blanco). */
export function parrafos(texto: string): string[] {
  return texto
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)
}

/** Fecha calendario en San Juan de un instante UTC: "25/10/2026". */
export function fechaLocal(iso: string): string {
  return new Intl.DateTimeFormat('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'America/Argentina/San_Juan',
  }).format(new Date(iso))
}

/** Ruta del enlace canónico para navegar dentro del mismo sitio (el absoluto sale de
 * PUBLIC_WEB_URL y es el que se comparte). */
export function rutaLocal(url: string): string {
  try {
    return new URL(url).pathname
  } catch {
    return url
  }
}
