import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as ddjjApi from '../ddjj/api'
import { DeclaracionPage } from '../ddjj/DeclaracionPage'
import * as pagosApi from './api'
import { ComprobantePage } from './ComprobantePage'
import { RetornoMercadoPagoPage } from './RetornoMercadoPagoPage'

vi.mock('./api')
vi.mock('../ddjj/api')

const NOTARIO = {
  ...ESCRIBANO,
  permissions: ['ddjj:read_own', 'ddjj:create_own', 'boletas:read_own', 'comprobantes:upload'],
}
const REGISTRO = { id: 'r1', numero_registro: 51, nombre_fantasia: null, departamento: 'Capital' }

const BOLETA: ddjjApi.Boleta = {
  id: 'b1',
  numero: 1069,
  codigo_verificacion: 'ABCDEFGH23456723',
  ddjj_id: 'd1',
  registro: REGISTRO,
  periodo: '2026-09',
  numero_rectificativa: 0,
  estado: 'PENDIENTE',
  fecha_emision: '2026-10-23',
  fecha_vencimiento: '2026-10-28',
  fecha_pago: '2099-12-31',
  dias_mora: 0,
  total_protocolos: '984699.06',
  aporte_minimo: '85932.00',
  excedente: '898767.06',
  aporte_medico: '200000.00',
  cantidad_aportes_medicos: 2,
  total_en_termino: '1184699.06',
  interes_mora: '0.00',
  tramos_mora: [],
  total_a_pagar: '1184699.06',
  created_at: '2026-10-23T12:00:00Z',
  emitida_por: 'Caja Notarial',
  anulada_en: null,
  motivo_anulacion: null,
  comprobante: null,
}

const DDJJ = {
  id: 'd1',
  registro: REGISTRO,
  periodo: '2026-09',
  numero_rectificativa: 0,
  estado: 'PRESENTADA',
  observaciones: null,
  fecha_presentacion: '2026-10-23T12:00:00Z',
  presentada_por: 'Escribano Demo',
  rectifica_a_id: null,
  cantidad_actos: 0,
  total_protocolos: '984699.06',
  vencimiento: '2026-10-28',
  created_at: '2026-10-01T12:00:00Z',
  actos: [],
  boletas: [BOLETA],
  escribanos: [],
  puede_operar: true,
  controles: {},
  huecos: [],
  proximos_numeros: { GENERAL: 1, AUXILIAR: 1 },
} as unknown as ddjjApi.DeclaracionDetalle

const PAGO: pagosApi.PagoMercadoPago = {
  id: 'p1',
  boleta_id: 'b1',
  estado: 'approved',
  estado_detalle: 'accredited',
  mp_payment_id: '123456789',
  medio_pago: 'account_money',
  importe_boleta: '1184699.06',
  importe_pagado: '1184699.06',
  comision: '1234.56',
  importe_neto: '1183464.50',
  aprobado_en: '2026-10-23T13:15:00Z',
  comprobante_id: 'c1',
  created_at: '2026-10-23T13:00:00Z',
}

describe('pagar una boleta con Mercado Pago', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(ddjjApi.fetchDeclaracion).mockResolvedValue(DDJJ)
  })

  it('ofrece el pago y lleva a Mercado Pago', async () => {
    vi.mocked(pagosApi.fetchMercadoPagoHabilitado).mockResolvedValue(true)
    vi.mocked(pagosApi.pagarConMercadoPago).mockResolvedValue('https://mp.test/checkout/1')
    const assign = vi.fn()
    vi.stubGlobal('location', {
      assign,
      href: window.location.href,
      origin: window.location.origin,
    })
    renderWithProviders(
      <Routes>
        <Route path="/ddjj/:id" element={<DeclaracionPage />} />
      </Routes>,
      { path: '/ddjj/d1', user: NOTARIO, raw: true },
    )

    fireEvent.click(await screen.findByRole('button', { name: 'Pagar con Mercado Pago' }))
    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith('https://mp.test/checkout/1')
    })
    expect(pagosApi.pagarConMercadoPago).toHaveBeenCalledWith('b1')
    vi.unstubAllGlobals()
  })

  it('sin Mercado Pago configurado no aparece; con un pago en revisión, tampoco', async () => {
    vi.mocked(pagosApi.fetchMercadoPagoHabilitado).mockResolvedValue(false)
    const { unmount } = renderWithProviders(
      <Routes>
        <Route path="/ddjj/:id" element={<DeclaracionPage />} />
      </Routes>,
      { path: '/ddjj/d1', user: NOTARIO, raw: true },
    )
    expect(await screen.findByText('Boleta N° 1069')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pagar con Mercado Pago' })).not.toBeInTheDocument()
    unmount()

    vi.mocked(pagosApi.fetchMercadoPagoHabilitado).mockResolvedValue(true)
    vi.mocked(ddjjApi.fetchDeclaracion).mockResolvedValue({
      ...DDJJ,
      boletas: [
        {
          ...BOLETA,
          comprobante: {
            id: 'c1',
            origen: 'MERCADO_PAGO',
            estado: 'PENDIENTE_REVISION',
            importe_declarado: '1184699.06',
            motivo_rechazo: null,
            created_at: '2026-10-23T13:15:00Z',
          },
        },
      ],
    })
    renderWithProviders(
      <Routes>
        <Route path="/ddjj/:id" element={<DeclaracionPage />} />
      </Routes>,
      { path: '/ddjj/d1', user: NOTARIO, raw: true },
    )
    expect(await screen.findByText('Pago con Mercado Pago en revisión')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pagar con Mercado Pago' })).not.toBeInTheDocument()
  })
})

describe('vuelta desde Mercado Pago', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(ddjjApi.fetchBoleta).mockResolvedValue(BOLETA)
  })

  function renderRetorno() {
    return renderWithProviders(
      <Routes>
        <Route path="/pagos/mercadopago/retorno" element={<RetornoMercadoPagoPage />} />
      </Routes>,
      { path: '/pagos/mercadopago/retorno?pago=p1&status=approved', user: NOTARIO, raw: true },
    )
  }

  it('consulta el pago a la Suite (no a la dirección) y explica que lo confirma Tesorería', async () => {
    vi.mocked(pagosApi.sincronizarPagoMP).mockResolvedValue(PAGO)
    renderRetorno()
    expect(await screen.findByText('Mercado Pago aprobó tu pago')).toBeInTheDocument()
    expect(screen.getByText(/Tesorería lo confirma/)).toBeInTheDocument()
    expect(pagosApi.sincronizarPagoMP).toHaveBeenCalledWith('p1')
    expect(await screen.findByRole('link', { name: /Volver a la declaración/ })).toHaveAttribute(
      'href',
      '/ddjj/d1',
    )
  })

  it('aunque la dirección diga «approved», si Mercado Pago lo rechazó se informa el rechazo', async () => {
    vi.mocked(pagosApi.sincronizarPagoMP).mockResolvedValue({
      ...PAGO,
      estado: 'rejected',
      comprobante_id: null,
    })
    renderRetorno()
    expect(await screen.findByText('Mercado Pago no aprobó el pago')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Consultar de nuevo' })).toBeInTheDocument()
  })
})

describe('ficha de Tesorería', () => {
  it('un pago de Mercado Pago muestra sus datos y no busca un archivo', async () => {
    vi.resetAllMocks()
    vi.mocked(pagosApi.fetchComprobante).mockResolvedValue({
      id: 'c1',
      boleta: {
        id: 'b1',
        numero: 1069,
        ddjj_id: 'd1',
        registro: REGISTRO,
        periodo: '2026-09',
        estado: 'PENDIENTE',
        fecha_pago: '2099-12-31',
        total_a_pagar: '1184699.06',
      },
      origen: 'MERCADO_PAGO',
      nombre_original: null,
      mime_type: null,
      tamano_bytes: null,
      fecha_transferencia: '2026-10-23',
      banco_origen: 'Mercado Pago',
      numero_operacion: '123456789',
      importe_declarado: '1184699.06',
      diferencia: '0.00',
      estado: 'PENDIENTE_REVISION',
      motivo_rechazo: null,
      subido_por: 'escribano@suite-notarial.example',
      created_at: '2026-10-23T13:15:00Z',
      revisado_en: null,
      conciliacion: null,
      mercado_pago: PAGO,
    })
    renderWithProviders(
      <Routes>
        <Route path="/tesoreria/conciliacion/:id" element={<ComprobantePage />} />
      </Routes>,
      {
        path: '/tesoreria/conciliacion/c1',
        raw: true,
        user: { ...ESCRIBANO, permissions: ['comprobantes:verify'] },
      },
    )
    expect(await screen.findByText('Pago con Mercado Pago')).toBeInTheDocument()
    expect(screen.getByText('$ 1.234,56')).toBeInTheDocument()
    expect(screen.getByText('$ 1.183.464,50')).toBeInTheDocument()
    expect(pagosApi.fetchArchivo).not.toHaveBeenCalled()
  })
})
