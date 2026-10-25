import { describe, expect, it } from 'vitest'

import { parseHealth } from './api'

describe('parseHealth', () => {
  it('acepta una respuesta válida', () => {
    const health = parseHealth({ status: 'ok', db: 'up', time_utc: '2026-10-25T13:00:00Z' })
    expect(health).toEqual({ status: 'ok', db: 'up', timeUtc: new Date('2026-10-25T13:00:00Z') })
  })

  it.each([
    null,
    'ok',
    { status: 'bien', db: 'up', time_utc: '2026-10-25T13:00:00Z' },
    { status: 'ok', db: 'arriba', time_utc: '2026-10-25T13:00:00Z' },
    { status: 'ok', db: 'up', time_utc: 'ayer' },
    { status: 'ok', db: 'up' },
  ])('rechaza payload inválido %#', (payload) => {
    expect(() => parseHealth(payload)).toThrow()
  })
})
