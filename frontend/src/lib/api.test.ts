import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'

import { rutaInsegura, toProblem } from './api'

function axiosError(status: number, data: unknown) {
  return new AxiosError('x', 'ERR', undefined, undefined, {
    status,
    statusText: '',
    headers: {},
    config: { headers: new AxiosHeaders() },
    data,
  })
}

describe('toProblem', () => {
  it('lee Problem Details y errores por campo', () => {
    const problem = toProblem(
      axiosError(422, {
        status: 422,
        title: 'Unprocessable Content',
        detail: 'La solicitud contiene datos inválidos.',
        errors: [{ loc: ['body', 'cuit'], msg: 'Value error, El CUIT debe tener 11 dígitos.' }],
      }),
    )
    expect(problem.status).toBe(422)
    expect(problem.fieldErrors).toEqual({ cuit: 'El CUIT debe tener 11 dígitos.' })
  })

  it('traduce la falta de respuesta a un error de conexión', () => {
    expect(toProblem(new AxiosError('Network Error')).status).toBe(0)
  })
})

describe('rutaInsegura', () => {
  it('rechaza segmentos . y .. (también codificados) y barras dentro de un id', () => {
    expect(rutaInsegura('/v1/pagos/mercadopago/../../comprobantes/x/aprobar')).toBe(true)
    expect(rutaInsegura('/v1/pagos/mercadopago/%2e%2e/x')).toBe(true)
    expect(rutaInsegura('/v1/pagos/mercadopago/a%2Fb/sincronizar')).toBe(true)
    expect(rutaInsegura('/v1/ddjj/boletas/%E0%A4%A')).toBe(true)
  })

  it('deja pasar las rutas normales, con o sin parámetros', () => {
    expect(
      rutaInsegura('/v1/pagos/mercadopago/3f1c2b9a-7d4e-4a51-9c3b-2e8f6a1d0b7c/sincronizar'),
    ).toBe(false)
    expect(rutaInsegura('/v1/cms/novedades?page=1&estado=PUBLICADO')).toBe(false)
  })
})
