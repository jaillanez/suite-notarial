import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as padronApi from './api'
import { EscribanoNuevoPage } from './EscribanoNuevoPage'
import { EscribanosPage } from './EscribanosPage'
import { formatDate } from './labels'

vi.mock('./api')

const CAJA = {
  ...ESCRIBANO,
  roles: ['ROLE_CAJA'],
  permissions: ['escribanos:read', 'escribanos:write', 'escribanos:status'],
}

describe('padrón', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(padronApi.fetchDepartamentos).mockResolvedValue(['Capital', 'Rivadavia'])
  })

  it('formatea fechas calendario sin corrimiento de zona', () => {
    expect(formatDate('2015-03-01')).toBe('01/03/2015')
    expect(formatDate(null)).toBe('—')
  })

  it('lista escribanos y filtra en el servidor', async () => {
    vi.mocked(padronApi.fetchEscribanos).mockResolvedValue({
      items: [
        {
          id: 'e1',
          matricula_numero: 101,
          tomo: null,
          folio: null,
          fecha_matriculacion: '2015-03-01',
          estado_matricula: 'SUSPENDIDO',
          apellido_nombre: 'Quiroga, Facundo',
          cuit: '20-00001400-2',
          numero_documento: '00001400',
          registro_actual: 2,
          cargo_actual: 'TITULAR',
          tiene_cuenta: false,
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
    })
    renderWithProviders(<EscribanosPage />, { path: '/padron/escribanos', user: CAJA })

    expect((await screen.findAllByText('Quiroga, Facundo')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Suspendido').length).toBeGreaterThan(0)

    fireEvent.change(screen.getByLabelText('Estado'), { target: { value: 'CESANTE' } })
    await waitFor(() => {
      expect(padronApi.fetchEscribanos).toHaveBeenLastCalledWith(
        expect.objectContaining({ estado: 'CESANTE', page: 1 }),
      )
    })
  })

  it('da de alta un escribano con persona y matrícula', async () => {
    vi.mocked(padronApi.createEscribano).mockResolvedValue({
      id: 'nuevo',
    } as padronApi.EscribanoDetalle)
    renderWithProviders(<EscribanoNuevoPage />, {
      path: '/padron/escribanos/nuevo',
      user: CAJA,
    })

    const type = (label: string, value: string) => {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
    type('Apellido', 'Sarmiento')
    type('Nombre', 'Domingo')
    type('CUIT', '20-30111222-0')
    type('Número', '30111222')
    type('Número de matrícula', '450')
    type('Fecha de matriculación', '2020-05-15')
    const submit = screen.getByRole('button', { name: 'Dar de alta' })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)
    await waitFor(() => {
      expect(padronApi.createEscribano).toHaveBeenCalled()
    })

    expect(padronApi.createEscribano).toHaveBeenCalledWith(
      expect.objectContaining({
        matricula_numero: 450,
        fecha_matriculacion: '2020-05-15',
        persona: expect.objectContaining({ apellido: 'Sarmiento', email: null }) as unknown,
      }),
    )
  })
})
