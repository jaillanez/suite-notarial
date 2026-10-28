import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as apiModule from './api'
import { ConceptoPage } from './ConceptoPage'
import { ParametrosPage } from './ParametrosPage'

vi.mock('./api')

const ADMIN = {
  ...ESCRIBANO,
  email: 'admin@suite-notarial.example',
  roles: ['ROLE_ADMIN'],
  permissions: ['parameters:read', 'parameters:write', 'parameters:approve'],
  mfa_enabled: true,
  mfa_required: true,
  mfa_verified: true,
}

const VIGENCIA: apiModule.Vigencia = {
  id: 'v1',
  concepto_id: 'c1',
  concepto_codigo: 'APORTE_ESCRITURA',
  version: 1,
  fecha_desde: '2026-01-01',
  fecha_hasta: null,
  porcentaje: '1.5000',
  monto_fijo: null,
  monto_minimo: '1000.00',
  monto_maximo: null,
  tasa: null,
  periodo_tasa: null,
  dias_gracia: null,
  regla_redondeo: 'HALF_UP',
  es_ejemplo: true,
  estado: 'VIGENTE',
  resolucion_respaldo: 'EJEMPLO',
  motivo: 'Valor de ejemplo',
  created_at: '2026-01-01T12:00:00Z',
  creado_por: 'otra@suite-notarial.example',
  aprobado_por: 'tesoreria@suite-notarial.example',
  fecha_aprobacion: '2026-01-01T13:00:00Z',
  motivo_rechazo: null,
}

const CONCEPTO: apiModule.Concepto = {
  id: 'c1',
  codigo: 'APORTE_ESCRITURA',
  nombre: 'Aporte sobre escrituras',
  tipo: 'PORCENTUAL_ACTO',
  descripcion: null,
  is_active: true,
  vigente: VIGENCIA,
  pendientes: 1,
}

describe('parámetros', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(apiModule.fetchConceptos).mockResolvedValue([CONCEPTO])
  })

  it('marca los valores a confirmar y las propuestas pendientes', async () => {
    renderWithProviders(<ParametrosPage />, { path: '/parametros', user: ADMIN })

    expect(await screen.findByText('Hay valores a confirmar')).toBeInTheDocument()
    expect(screen.getByText('1 propuesta pendiente de aprobación')).toBeInTheDocument()
    expect(screen.getByText('1,5 %')).toBeInTheDocument()
  })

  it('no deja aprobar la propuesta propia', async () => {
    vi.mocked(apiModule.fetchVigencias).mockResolvedValue([
      {
        ...VIGENCIA,
        id: 'v2',
        version: 2,
        fecha_desde: '2027-01-01',
        porcentaje: '1.7500',
        es_ejemplo: false,
        estado: 'PENDIENTE_APROBACION',
        creado_por: ADMIN.email,
        aprobado_por: null,
        fecha_aprobacion: null,
      },
    ])
    renderWithProviders(
      <Routes>
        <Route path="/parametros/:id" element={<ConceptoPage />} />
      </Routes>,
      { path: '/parametros/c1', user: ADMIN, raw: true },
    )

    expect(await screen.findByRole('button', { name: 'Aprobar' })).toBeDisabled()
    expect(screen.getByText('La propusiste vos: la aprueba otra persona.')).toBeInTheDocument()
  })

  function renderConcepto() {
    return renderWithProviders(
      <Routes>
        <Route path="/parametros/:id" element={<ConceptoPage />} />
      </Routes>,
      { path: '/parametros/c1', user: ADMIN, raw: true },
    )
  }

  it('«Cambiar valor» abre el formulario con el valor vigente precargado', async () => {
    vi.mocked(apiModule.fetchVigencias).mockResolvedValue([VIGENCIA])
    vi.mocked(apiModule.proponerVigencia).mockResolvedValue({
      ...VIGENCIA,
      id: 'v9',
      estado: 'PENDIENTE_APROBACION',
    })
    renderConcepto()

    fireEvent.click(await screen.findByRole('button', { name: 'Cambiar valor' }))
    expect(screen.getByLabelText('Porcentaje (%)')).toHaveValue('1,5')
    expect(screen.getByLabelText('Mínimo ($, opcional)')).toHaveValue('1000,00')
    fireEvent.change(screen.getByLabelText('Porcentaje (%)'), { target: { value: '1,75' } })
    fireEvent.change(screen.getByLabelText('Resolución que la respalda'), {
      target: { value: 'Res. 3/2027' },
    })
    fireEvent.change(screen.getByLabelText('Motivo'), { target: { value: 'Aumento anual' } })
    fireEvent.click(screen.getByRole('button', { name: 'Proponer' }))

    await waitFor(() => {
      expect(apiModule.proponerVigencia).toHaveBeenCalledWith(
        'c1',
        expect.objectContaining({ porcentaje: '1.75', monto_minimo: '1000.00' }),
      )
    })
  })

  it('una propuesta pendiente se corrige o se retira', async () => {
    const pendiente: apiModule.Vigencia = {
      ...VIGENCIA,
      id: 'v2',
      version: 2,
      fecha_desde: '2027-01-01',
      porcentaje: '1.7500',
      estado: 'PENDIENTE_APROBACION',
      creado_por: ADMIN.email,
      aprobado_por: null,
      fecha_aprobacion: null,
    }
    vi.mocked(apiModule.fetchVigencias).mockResolvedValue([pendiente, VIGENCIA])
    vi.mocked(apiModule.corregirVigencia).mockResolvedValue({ ...pendiente, id: 'v3', version: 3 })
    vi.mocked(apiModule.retirarVigencia).mockResolvedValue({ ...pendiente, estado: 'RETIRADA' })
    renderConcepto()

    fireEvent.click(await screen.findByRole('button', { name: 'Corregir' }))
    expect(screen.getByLabelText('Vigente desde')).toHaveValue('2027-01-01')
    fireEvent.change(screen.getByLabelText('Porcentaje (%)'), { target: { value: '1,8' } })
    fireEvent.change(screen.getByLabelText('Qué se corrige'), {
      target: { value: 'Era 1,8 y no 1,75' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Guardar corrección' }))
    await waitFor(() => {
      expect(apiModule.corregirVigencia).toHaveBeenCalledWith(
        'v2',
        expect.objectContaining({ porcentaje: '1.8', fecha_desde: '2027-01-01' }),
      )
    })

    fireEvent.click(screen.getByRole('button', { name: 'Retirar' }))
    fireEvent.change(screen.getByLabelText('Por qué se retira'), {
      target: { value: 'Ya no corresponde' },
    })
    fireEvent.click(screen.getAllByRole('button', { name: 'Retirar' }).at(-1) as HTMLElement)
    await waitFor(() => {
      expect(apiModule.retirarVigencia).toHaveBeenCalledWith('v2', 'Ya no corresponde')
    })
  })
})
