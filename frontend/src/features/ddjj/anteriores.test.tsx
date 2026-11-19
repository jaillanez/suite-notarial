import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as api from './api'
import { AnterioresPanel, DDJJAnteriorPage } from './DDJJAnteriores'

vi.mock('./api')

const PAGADA: api.DDJJAnterior = {
  registro_id: 'r1',
  numero_registro: 51,
  periodo: '2025-09',
  cantidad_actos: 2,
  total_aportes: '209922.00',
  total_boletas: '295854.00',
  total_pagado: '295854.00',
}

describe('DDJJ del sistema anterior', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('lista las DDJJ anteriores con su estado de pago y filtra por registro', async () => {
    vi.mocked(api.fetchAnteriores).mockResolvedValue({
      items: [
        PAGADA,
        { ...PAGADA, periodo: '2025-10', cantidad_actos: 0, total_pagado: '0.00' },
        { ...PAGADA, periodo: '2025-08', total_pagado: '100000.00' },
      ],
      total: 3,
      page: 1,
      page_size: 20,
    })
    renderWithProviders(<AnterioresPanel />, { user: ESCRIBANO })

    expect(await screen.findByText('Pagada')).toBeInTheDocument()
    expect(screen.getByText('Del sistema anterior')).toBeInTheDocument()
    expect(screen.getByText('Impaga')).toBeInTheDocument()
    expect(screen.getByText('Pago parcial')).toBeInTheDocument()
    expect(screen.getAllByRole('link')[0]).toHaveAttribute('href', '/ddjj/anterior/r1/2025-09')

    fireEvent.change(screen.getByLabelText('N° de registro'), { target: { value: '51' } })
    await waitFor(() => {
      expect(api.fetchAnteriores).toHaveBeenLastCalledWith(
        expect.objectContaining({ registro: '51', page: 1 }),
      )
    })
  })

  it('sin DDJJ anteriores no muestra la sección', async () => {
    vi.mocked(api.fetchAnteriores).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    })
    renderWithProviders(<AnterioresPanel />, { user: ESCRIBANO })
    await waitFor(() => {
      expect(api.fetchAnteriores).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.queryByText('Del sistema anterior')).not.toBeInTheDocument()
    })
  })

  it('el detalle muestra los actos y las boletas, de solo lectura', async () => {
    vi.mocked(api.fetchAnterior).mockResolvedValue({
      resumen: PAGADA,
      actos: [
        {
          id: 'a1',
          tipo_protocolo: 'GENERAL',
          numero_escritura: 101,
          folio: 3,
          fecha_acto: '2025-09-10',
          naturaleza: 'Compraventa',
          escribano: 'ORIGEN, Escribano',
          cargo: 'TITULAR',
          exento: false,
          base_imponible: '50000000.00',
          aporte_variable: '200000.00',
          aporte_fijo: null,
          aporte: '200000.00',
        },
      ],
      boletas: [
        {
          id: 'b1',
          numero: 'L-2025-09',
          fecha_emision: '2025-09-28',
          fecha_vencimiento: '2025-10-15',
          importe: '295854.00',
          estado: 'PAGADA',
          pagado: '295854.00',
          fecha_pago: '2025-10-10',
        },
      ],
    })
    renderWithProviders(
      <Routes>
        <Route path="/ddjj/anterior/:registroId/:periodo" element={<DDJJAnteriorPage />} />
      </Routes>,
      { path: '/ddjj/anterior/r1/2025-09', user: ESCRIBANO, raw: true },
    )

    expect(await screen.findByRole('heading', { name: 'DDJJ 09/2025' })).toBeInTheDocument()
    expect(screen.getByText(/solo lectura/)).toBeInTheDocument()
    expect(screen.getByText('Compraventa')).toBeInTheDocument()
    expect(screen.getByText('Boleta L-2025-09')).toBeInTheDocument()
    expect(screen.getByText(/Pagada el 10\/10\/2025/)).toBeInTheDocument()
    expect(api.fetchAnterior).toHaveBeenCalledWith('r1', '2025-09')
    // Nada que editar: sin botones de carga.
    expect(screen.queryByRole('button', { name: /Agregar/ })).not.toBeInTheDocument()
  })
})
