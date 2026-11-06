import type { Tone } from '../../components/StatusIndicator'
import type { CampoACompletar, Cargo, EstadoMatricula, EstadoRegistro } from './api'

export const ESTADO_MATRICULA: Record<EstadoMatricula, { label: string; tone: Tone }> = {
  ACTIVO: { label: 'Activo', tone: 'success' },
  SUSPENDIDO: { label: 'Suspendido', tone: 'warning' },
  CESANTE: { label: 'Cesante', tone: 'danger' },
  JUBILADO: { label: 'Jubilado', tone: 'unknown' },
  FALLECIDO: { label: 'Fallecido', tone: 'unknown' },
}

export const ESTADO_REGISTRO: Record<EstadoRegistro, { label: string; tone: Tone }> = {
  ACTIVO: { label: 'Con titular', tone: 'success' },
  VACANTE: { label: 'Vacante', tone: 'warning' },
  CERRADO: { label: 'Cerrado', tone: 'unknown' },
}

export const CARGO: Record<Cargo, string> = {
  TITULAR: 'Titular',
  ADSCRIPTO: 'Adscripto',
  SUPLENTE_INTERINO: 'A cargo',
}

/** Dato que faltaba en el sistema anterior y la Caja todavía no cargó. */
export const A_COMPLETAR = 'A completar'
export const CUIT_A_COMPLETAR = 'CUIT a completar'

export const CAMPO_A_COMPLETAR: Record<CampoACompletar, string> = {
  matricula_numero: 'Matrícula',
  fecha_matriculacion: 'Fecha de matriculación',
  cuit: 'CUIT',
  numero_documento: 'DNI',
}

/** Matrícula para mostrar: el número o «A completar». */
export function matriculaTexto(numero: number | null): string {
  return numero === null ? A_COMPLETAR : String(numero)
}

export const ESTADOS_DEFINITIVOS: EstadoMatricula[] = ['CESANTE', 'JUBILADO', 'FALLECIDO']

export const DATE_FORMAT = new Intl.DateTimeFormat('es-AR', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'UTC',
})

/** Fecha calendario (YYYY-MM-DD) sin corrimiento por zona horaria. */
export function formatDate(value: string | null): string {
  if (!value) return '—'
  return DATE_FORMAT.format(new Date(`${value}T00:00:00Z`))
}

export function todayIso(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Argentina/San_Juan' }).format(
    new Date(),
  )
}
