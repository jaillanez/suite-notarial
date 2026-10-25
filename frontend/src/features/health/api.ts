import { api } from '../../lib/api'

export type HealthStatus = 'ok' | 'degraded'
export type DbState = 'up' | 'down'

export interface Health {
  status: HealthStatus
  db: DbState
  timeUtc: Date
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** Valida en runtime la respuesta: el contrato del backend no se asume, se verifica. */
export function parseHealth(payload: unknown): Health {
  if (!isRecord(payload)) throw new Error('Respuesta de salud inválida')
  const { status, db, time_utc: timeUtc } = payload
  if (status !== 'ok' && status !== 'degraded') throw new Error('Campo "status" inválido')
  if (db !== 'up' && db !== 'down') throw new Error('Campo "db" inválido')
  if (typeof timeUtc !== 'string') throw new Error('Campo "time_utc" inválido')
  const date = new Date(timeUtc)
  if (Number.isNaN(date.getTime())) throw new Error('Campo "time_utc" no es una fecha')
  return { status, db, timeUtc: date }
}

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await api.get<unknown>('/health', { signal })
  return parseHealth(response.data)
}
