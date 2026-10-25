import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import { formatMoney } from '../../lib/decimal'
import * as apiModule from './api'
import { ComprobantePage } from './ComprobantePage'
import { ConciliacionPage } from './ConciliacionPage'
import { formatTamano } from './labels'

vi.mock('./api')

const TESORERIA = {
  ...ESCRIBANO,
  email: 'tesoreria@suite-notarial.example',
  roles: ['ROLE_TESORERIA'],
  permissions: ['comprobantes:verify', 'boletas:read_all'],
}

const COMPROBANTE: apiModule.Comprobante = {
  id: 'c1',
  boleta: {
    id: 'b1',
    numero: 1069,
    ddjj_id: 'd1',
    registro: { id: 'r1', numero_registro: 51, nombre_fantasia: null, departamento: 'Capital' },
    periodo: '2026-09',
    estado: 'PENDIENTE',
    fecha_pago: '2026-10-23',
    total_a_pagar: '1081699.06',
  },
  nombre_original: 'transferencia.pdf',
  mime_type: 'application/pdf',
  tamano_bytes: 2048,
  fecha_transferencia: '2026-10-23',
  banco_origen: null,
  numero_operacion: 'OP-1',
  importe_declarado: '1000000.00',
  diferencia: '-81699.06',
  estado: 'PENDIENTE_REVISION',
  motivo_rechazo: null,
  subido_por: 'escribano@suite-notarial.example',
  created_at: '2026-10-23T12:00:00Z',
  revisado_en: null,
  conciliacion: null,
}

describe('formatos', () => {
  it('importes negativos con el signo antes del símbolo y tamaños legibles', () => {
    expect(formatMoney('-81699.06')).toBe('−$ 81.699,06')
    expect(formatTamano(2048)).toBe('2 KB')
    expect(formatTamano(1468006)).toBe('1,4 MB')
  })
})

describe('mesa de conciliación', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('lista los comprobantes en revisión y resalta la diferencia', async () => {
    vi.mocked(apiModule.fetchMesa).mockResolvedValue({
      items: [COMPROBANTE],
      total: 1,
      page: 1,
      page_size: 20,
    })

    renderWithProviders(<ConciliacionPage />, { path: '/tesoreria/conciliacion', user: TESORERIA })

    expect(await screen.findByText('1 comprobante espera revisión.')).toBeInTheDocument()
    expect(screen.getByText(/Diferencia −\$ 81\.699,06/)).toBeInTheDocument()
  })

  it('el rechazo exige motivo y un motivo frecuente lo completa', async () => {
    vi.mocked(apiModule.fetchComprobante).mockResolvedValue(COMPROBANTE)
    vi.mocked(apiModule.fetchArchivo).mockResolvedValue(new Blob(['%PDF-1.4']))
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:comprobante')
    globalThis.URL.revokeObjectURL = vi.fn()
    vi.mocked(apiModule.rechazarComprobante).mockResolvedValue({
      ...COMPROBANTE,
      estado: 'RECHAZADO',
    })

    renderWithProviders(
      <Routes>
        <Route path="/tesoreria/conciliacion/:id" element={<ComprobantePage />} />
      </Routes>,
      { path: '/tesoreria/conciliacion/c1', user: TESORERIA, raw: true },
    )

    const rechazar = await screen.findByRole('button', { name: 'Rechazar comprobante' })
    expect(rechazar).toBeDisabled()
    expect(screen.getByText('Diferencia')).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', {
        name: 'El importe transferido no coincide con el total de la boleta.',
      }),
    )
    expect(rechazar).toBeEnabled()
    fireEvent.click(rechazar)
    await waitFor(() => {
      expect(apiModule.rechazarComprobante).toHaveBeenCalledWith(
        'c1',
        'El importe transferido no coincide con el total de la boleta.',
      )
    })
  })

  it('aprobar fuera de plazo exige observaciones', async () => {
    vi.mocked(apiModule.fetchComprobante).mockResolvedValue({
      ...COMPROBANTE,
      importe_declarado: '1081699.06',
      diferencia: '0.00',
    })
    vi.mocked(apiModule.fetchArchivo).mockResolvedValue(new Blob(['%PDF-1.4']))
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:comprobante')
    globalThis.URL.revokeObjectURL = vi.fn()

    renderWithProviders(
      <Routes>
        <Route path="/tesoreria/conciliacion/:id" element={<ComprobantePage />} />
      </Routes>,
      { path: '/tesoreria/conciliacion/c1', user: TESORERIA, raw: true },
    )

    const confirmar = await screen.findByRole('button', { name: 'Confirmar pago' })
    expect(screen.getByText('Coincide con el total')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Importe acreditado ($)'), {
      target: { value: '1.081.699,06' },
    })
    fireEvent.change(screen.getByLabelText('Fecha de acreditación'), {
      target: { value: '2026-10-27' },
    })
    expect(confirmar).toBeDisabled()
    expect(screen.getByText(/Se acreditó después de la fecha de pago/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Observaciones'), {
      target: { value: 'Demora bancaria informada.' },
    })
    expect(confirmar).toBeEnabled()
  })
})
