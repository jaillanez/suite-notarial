import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as apiModule from './api'
import { formatCelda } from './formato'
import { ReportePage } from './ReportePage'

vi.mock('./api')

const AUDITOR = {
  ...ESCRIBANO,
  roles: ['ROLE_AUDITOR'],
  permissions: ['reports:financial', 'audit:read'],
}

const BOLETAS: apiModule.Reporte = {
  codigo: 'BOLETAS',
  titulo: 'Boletas emitidas',
  descripcion: 'Boletas con su desglose.',
  sensible: false,
  columnas: [
    { key: 'numero', label: 'N°', tipo: 'ENTERO', total: false, visible: true },
    { key: 'periodo', label: 'Período', tipo: 'PERIODO', total: false, visible: true },
    { key: 'estado', label: 'Estado', tipo: 'TEXTO', total: false, visible: true },
    { key: 'excedente', label: 'Excedente', tipo: 'MONEDA', total: true, visible: false },
    { key: 'total_a_pagar', label: 'Total', tipo: 'MONEDA', total: true, visible: true },
  ],
  filtros: [
    {
      key: 'estado',
      label: 'Estado',
      tipo: 'OPCIONES',
      opciones: [
        { value: 'PAGADA', label: 'Pagada' },
        { value: 'PENDIENTE', label: 'Pendiente de pago' },
      ],
      ayuda: null,
    },
  ],
}

function col(key: string): apiModule.Columna {
  const found = BOLETAS.columnas.find((c) => c.key === key)
  if (!found) throw new Error(key)
  return found
}

function renderReporte() {
  return renderWithProviders(
    <Routes>
      <Route path="/reportes/:codigo" element={<ReportePage />} />
    </Routes>,
    { path: '/reportes/boletas', user: AUDITOR, raw: true },
  )
}

describe('formato de celdas', () => {
  it('formatea según el tipo, sin float', () => {
    expect(formatCelda(col('total_a_pagar'), '1081699.06')).toBe('$ 1.081.699,06')
    expect(formatCelda(col('periodo'), '2026-09')).toBe('09/2026')
    expect(formatCelda(col('estado'), 'PENDIENTE_REVISION')).toBe('Pendiente revision')
    expect(formatCelda({ ...col('numero'), tipo: 'CUIT' }, '20123456789')).toBe('20-12345678-9')
    expect(formatCelda(col('total_a_pagar'), null)).toBe('—')
  })
})

describe('reporte genérico', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    localStorage.clear()
    vi.mocked(apiModule.fetchReportes).mockResolvedValue([BOLETAS])
    vi.mocked(apiModule.fetchPagina).mockResolvedValue({
      items: [
        {
          numero: 1069,
          periodo: '2026-09',
          estado: 'PAGADA',
          excedente: '898767.06',
          total_a_pagar: '1081699.06',
        },
      ],
      total: 30,
      page: 1,
      page_size: 25,
      totales: { excedente: '9000000.00', total_a_pagar: '12345678.90' },
    })
    vi.mocked(apiModule.exportar).mockResolvedValue()
  })

  it('muestra los totales de todas las filas y oculta las columnas no elegidas', async () => {
    renderReporte()

    expect(await screen.findAllByText('$ 12.345.678,90')).not.toHaveLength(0)
    expect(screen.getAllByText('Total · 30 filas').length).toBeGreaterThan(0)
    const tabla = screen.getByRole('table')
    expect(within(tabla).queryByText('Excedente')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Columnas/ }))
    fireEvent.click(screen.getByLabelText('Excedente'))

    expect(within(screen.getByRole('table')).getByText('Excedente')).toBeInTheDocument()
    expect(localStorage.getItem('suite:reporte:BOLETAS:columnas')).toContain('excedente')
  })

  it('filtra en el servidor y exporta con los mismos filtros', async () => {
    renderReporte()
    await screen.findByRole('table')

    fireEvent.change(screen.getByRole('combobox', { name: 'Estado' }), {
      target: { value: 'PAGADA' },
    })
    await waitFor(() => {
      expect(apiModule.fetchPagina).toHaveBeenLastCalledWith('BOLETAS', { estado: 'PAGADA' }, 1, 25)
    })
    fireEvent.click(screen.getByRole('button', { name: 'Excel' }))

    await waitFor(() => {
      expect(apiModule.exportar).toHaveBeenCalledWith('BOLETAS', { estado: 'PAGADA' }, 'xlsx')
    })
  })
})
