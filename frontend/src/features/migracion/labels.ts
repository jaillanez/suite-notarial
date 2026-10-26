import type { Tone } from '../../components/StatusIndicator'
import type { Area, Entidad, EstadoCorrida, ModoCorrida } from './api'

export const MODO: Record<ModoCorrida, string> = {
  SIMULACRO: 'Simulacro',
  DEFINITIVA: 'Carga definitiva',
}

export const ESTADO: Record<EstadoCorrida, { label: string; tone: Tone }> = {
  EN_CURSO: { label: 'En curso', tone: 'unknown' },
  SIMULADA: { label: 'Simulada', tone: 'success' },
  CARGADA: { label: 'Cargada', tone: 'success' },
  FALLIDA: { label: 'Fallida', tone: 'danger' },
}

export const AREA: Record<Area, string> = { TESORERIA: 'Tesorería', CAJA: 'Caja' }

/** Rol que firma por cada área (mismo criterio que el backend). */
export const ROL_DEL_AREA: Record<Area, string> = {
  TESORERIA: 'ROLE_TESORERIA',
  CAJA: 'ROLE_CAJA',
}

export const ENTIDAD: Record<Entidad, string> = {
  registros: 'Registros',
  escribanos: 'Escribanos',
  cargos: 'Cargos',
  boletas: 'Boletas',
  pagos: 'Pagos',
}

export const ESTADO_BOLETA_HISTORICA: Record<string, string> = {
  IMPAGA: 'Impagas',
  PAGADA: 'Pagadas',
  ANULADA: 'Anuladas',
}

export function huellaCorta(huella: string): string {
  return huella.slice(0, 12)
}

export const TABLA_HOMOLOGACION: Record<string, string> = {
  estado_escribano: 'Estado de matrícula',
  estado_registro: 'Estado del registro',
  cargo: 'Cargo en el registro',
  estado_boleta: 'Estado de la boleta',
}
