import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'

import { toProblem } from './api'

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
