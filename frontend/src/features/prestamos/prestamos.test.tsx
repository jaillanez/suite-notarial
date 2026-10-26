import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as apiModule from './api'
import { ResumenEvaluacion } from './componentes'
import { PrestamoPage } from './PrestamoPage'

vi.mock('./api')

const CUOTA: apiModule.Cuota = {
  numero: 1,
  vencimiento: '2026-11-23',
  saldo_inicial: '100000.00',
  amortizacion: '7884.88',
  interes: '1000.00',
  cuota: '8884.88',
  saldo_final: '92115.12',
  estado: 'PENDIENTE',
  vencida: true,
  fecha_pago: null,
  importe_pagado: null,
}

const EV: apiModule.Evaluacion = {
  sistema: 'FRANCES',
  tna: '12.0000',
  tasa_es_ejemplo: true,
  capital: '100000.00',
  cuotas: 12,
  cuota_maxima: '8884.88',
  otras_cuotas: '0.00',
  afectacion: '35.5396',
  afectacion_maxima: '30.0000',
  requiere_garante: false,
  impedimentos: ['La cuota compromete el 35,5396 % del ingreso neto.'],
  plan: [CUOTA],
  totales: { capital: '100000.00', intereses: '6618.53', total: '106618.53' },
}

describe('evaluación', () => {
  it('avisa tasa a confirmar, motivos y afectación sobre el tope', () => {
    renderWithProviders(<ResumenEvaluacion ev={EV} conIngreso />)

    expect(screen.getByText('Tasa a confirmar')).toBeInTheDocument()
    expect(screen.getByText('No se puede otorgar con estos datos')).toBeInTheDocument()
    expect(screen.getByText('35,5396 %')).toBeInTheDocument()
    expect(screen.getByText('$ 106.618,53')).toBeInTheDocument()
  })
})

describe('ficha del préstamo', () => {
  const BASE: apiModule.PrestamoDetalle = {
    id: 'p1',
    numero: 7,
    escribano: { id: 'e1', apellido_nombre: 'Sintético, Escribano', matricula_numero: 101 },
    garante: null,
    linea_id: 'l1',
    linea_nombre: 'Línea común',
    estado: 'SOLICITADO',
    sistema: 'FRANCES',
    tna: '12.0000',
    tasa_es_ejemplo: false,
    capital: '100000.00',
    cuotas: 12,
    ingreso_neto: '60000.00',
    otras_cuotas: '0.00',
    cuota_maxima: '8884.88',
    afectacion: '14.8082',
    afectacion_maxima: '30.0000',
    observaciones: null,
    motivo_rechazo: null,
    fecha_otorgamiento: null,
    creado_por: 'caja@suite-notarial.example',
    resuelto_por: null,
    resuelto_en: null,
    created_at: '2026-10-23T12:00:00Z',
    saldo_capital: null,
    cuotas_pagadas: 0,
    cuotas_vencidas: 0,
    plan: [{ ...CUOTA, vencida: false }],
    totales: EV.totales,
    impedimentos_actuales: [],
    puede_resolver: false,
  }

  function renderFicha(permisos: string[]) {
    return renderWithProviders(
      <Routes>
        <Route path="/prestamos/:id" element={<PrestamoPage />} />
      </Routes>,
      { path: '/prestamos/p1', raw: true, user: { ...ESCRIBANO, permissions: permisos } },
    )
  }

  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('solo ofrece otorgar a quien puede resolver (cuatro ojos)', async () => {
    vi.mocked(apiModule.fetchPrestamo).mockResolvedValue(BASE)
    renderFicha(['prestamos:read_all', 'prestamos:approve'])

    expect(await screen.findByText('Préstamo N° 7')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Otorgar préstamo' })).not.toBeInTheDocument()
    expect(screen.getByText(/la resuelve otra persona/)).toBeInTheDocument()
  })

  it('con permiso y otra persona, ofrece otorgar; Tesorería ve el cobro de la próxima cuota', async () => {
    vi.mocked(apiModule.fetchPrestamo).mockResolvedValue({ ...BASE, puede_resolver: true })
    const { unmount } = renderFicha(['prestamos:read_all', 'prestamos:approve'])
    expect(await screen.findByRole('button', { name: 'Otorgar préstamo' })).toBeEnabled()
    unmount()

    vi.mocked(apiModule.fetchPrestamo).mockResolvedValue({
      ...BASE,
      estado: 'OTORGADO',
      fecha_otorgamiento: '2026-10-23',
      cuotas_vencidas: 1,
      plan: [CUOTA],
    })
    renderFicha(['prestamos:read_all', 'prestamos:cobrar'])
    expect(
      await screen.findByRole('button', { name: 'Registrar pago de la cuota 1' }),
    ).toBeInTheDocument()
    expect(screen.getByText('1 cuota vencida')).toBeInTheDocument()
    expect(screen.getAllByText('Vencida').length).toBeGreaterThan(0)
  })
})
