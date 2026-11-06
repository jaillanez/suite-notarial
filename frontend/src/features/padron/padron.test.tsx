import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as padronApi from './api'
import { EscribanoNuevoPage } from './EscribanoNuevoPage'
import { EscribanoPage } from './EscribanoPage'
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

  it('muestra los datos a completar y los carga una vez', async () => {
    const migrado: padronApi.EscribanoDetalle = {
      id: 'e9',
      matricula_numero: null,
      tomo: null,
      folio: null,
      fecha_matriculacion: null,
      estado_matricula: 'ACTIVO',
      apellido_nombre: 'Sintético, Histórico',
      cuit: null,
      numero_documento: null,
      registro_actual: null,
      cargo_actual: null,
      tiene_cuenta: false,
      persona: {
        id: 'p9',
        cuit: null,
        tipo_documento: 'DNI',
        numero_documento: null,
        apellido: 'Sintético',
        nombre: 'Histórico',
        fecha_nacimiento: null,
        email: 'historico@ejemplo.test',
        telefono: null,
        domicilio_real: null,
      },
      transiciones_permitidas: [],
      transiciones_con_resolucion: [],
      motivo_ultimo_cambio_estado: null,
      fecha_ultimo_cambio_estado: null,
      a_completar: ['matricula_numero', 'fecha_matriculacion', 'cuit', 'numero_documento'],
      cargos: [],
      historial: [],
    }
    vi.mocked(padronApi.fetchEscribano).mockResolvedValue(migrado)
    vi.mocked(padronApi.completarEscribano).mockResolvedValue({
      ...migrado,
      matricula_numero: 512,
      a_completar: ['fecha_matriculacion', 'cuit', 'numero_documento'],
    })
    renderWithProviders(
      <Routes>
        <Route path="/padron/escribanos/:id" element={<EscribanoPage />} />
      </Routes>,
      {
        path: '/padron/escribanos/e9',
        user: { ...CAJA, permissions: [...CAJA.permissions, 'users:write'] },
        raw: true,
      },
    )

    expect(await screen.findByText('Matrícula a completar')).toBeInTheDocument()
    expect(screen.getByText('CUIT a completar')).toBeInTheDocument()
    expect(screen.getAllByText('A completar')).toHaveLength(4)
    // Sin CUIT no se puede crear la cuenta de autogestión.
    expect(screen.getByRole('button', { name: 'Crear cuenta de autogestión' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Completar datos' }))
    const guardar = screen.getByRole('button', { name: 'Guardar datos' })
    expect(guardar).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Matrícula'), { target: { value: '512' } })
    fireEvent.click(guardar)
    await waitFor(() => {
      expect(padronApi.completarEscribano).toHaveBeenCalledWith('e9', { matricula_numero: 512 })
    })
  })
})
