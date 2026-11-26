import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import { AjustesPage } from './AjustesPage'
import * as apiModule from './api'

vi.mock('./api')

const ADMIN = {
  ...ESCRIBANO,
  email: 'admin@suite-notarial.example',
  roles: ['ROLE_ADMIN'],
  permissions: ['ajustes:proponer', 'ajustes:aprobar'],
  mfa_enabled: true,
  mfa_required: true,
  mfa_verified: true,
}

const AJUSTE: apiModule.Ajuste = {
  id: 'a1',
  boleta_id: 'b1',
  boleta_numero: 1069,
  tipo: 'CREDITO',
  concepto: 'REDONDEO',
  importe: '0.02',
  justificacion: 'Pagó dos centavos de menos por redondeo del banco.',
  resolucion: null,
  estado: 'PROPUESTO',
  propuesto_por: 'caja@suite-notarial.example',
  propuesto_en: '2026-11-26T12:00:00Z',
  resuelto_por: null,
  resuelto_en: null,
  motivo_rechazo: null,
  puede_resolver: true,
}

const BOLETA: apiModule.BoletaParaAjustar = {
  boleta: {
    id: 'b1',
    numero: 1069,
    ddjj_id: 'd1',
    registro: { id: 'r1', numero_registro: 9999, nombre_fantasia: null, departamento: 'Capital' },
    periodo: '2026-09',
    estado: 'PENDIENTE',
    fecha_pago: '2026-10-23',
    total_a_pagar: '1081699.06',
    saldo_a_pagar: '1081699.04',
  },
  escribano: 'SINTÉTICO, Escribano',
  ajustes: [{ ...AJUSTE, estado: 'APROBADO', puede_resolver: false }],
}

describe('créditos y débitos', () => {
  beforeEach(() => {
    vi.mocked(apiModule.fetchAjustes).mockResolvedValue({
      items: [AJUSTE],
      total: 1,
      page: 1,
      page_size: 20,
    })
    vi.mocked(apiModule.fetchBoletaParaAjustar).mockResolvedValue(BOLETA)
    vi.mocked(apiModule.aprobarAjuste).mockResolvedValue({ ...AJUSTE, estado: 'APROBADO' })
  })

  it('lista los ajustes por aprobar y los aprueba quien no los propuso', async () => {
    renderWithProviders(<AjustesPage />, { path: '/ajustes', user: ADMIN })
    expect(
      await screen.findByText('Pagó dos centavos de menos por redondeo del banco.'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Aprobar' }))
    await waitFor(() => {
      expect(apiModule.aprobarAjuste).toHaveBeenCalledWith('a1')
    })
  })

  it('busca la boleta y muestra lo que queda pagar con sus ajustes', async () => {
    renderWithProviders(<AjustesPage />, { path: '/ajustes', user: ADMIN })
    fireEvent.change(screen.getByLabelText('N° de boleta'), { target: { value: '1069' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))
    expect(await screen.findByText('SINTÉTICO, Escribano', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('$ 1.081.699,04')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Proponer crédito o débito' })).toBeInTheDocument()
    expect(apiModule.fetchBoletaParaAjustar).toHaveBeenCalledWith(1069)
  })
})
