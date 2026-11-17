import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as ddjjApi from '../ddjj/api'
import { DeclaracionPage } from '../ddjj/DeclaracionPage'
import * as pagosApi from './api'

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
  escribano: {
    id: 'e1',
    apellido_nombre: 'SINTÉTICO, Escribano',
    cargo: 'TITULAR',
    modalidad: 'COMPLETA',
  },
  puede_reemitir: true,
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

const PUBLICADO: pagosApi.PagoSupervielle = {
  id: 'spv1',
  boleta_id: 'b1',
  id_publicacion: 1000,
  estado: 'CREADO',
  medio_pago: null,
  importe_boleta: '1184699.06',
  importe_pagado: null,
  comision_estimada: null,
  importe_neto_estimado: null,
  vence: '2099-12-31',
  pagado_en: null,
  comprobante_id: null,
  created_at: '2026-10-23T13:00:00Z',
}

function renderDeclaracion() {
  return renderWithProviders(
    <Routes>
      <Route path="/ddjj/:id" element={<DeclaracionPage />} />
    </Routes>,
    { path: '/ddjj/d1', user: NOTARIO, raw: true },
  )
}

describe('pagar una boleta con el botón Supervielle', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(ddjjApi.fetchDeclaracion).mockResolvedValue(DDJJ)
    vi.mocked(pagosApi.fetchMercadoPagoHabilitado).mockResolvedValue(false)
    vi.mocked(pagosApi.fetchSupervielleHabilitado).mockResolvedValue(true)
    vi.mocked(pagosApi.fetchPagosSupervielle).mockResolvedValue([])
  })

  it('abre el link del banco en otra pestaña y después verifica el pago', async () => {
    const pestana = { opener: {}, location: { href: '' }, close: vi.fn() }
    const open = vi.spyOn(window, 'open').mockReturnValue(pestana as unknown as Window)
    vi.mocked(pagosApi.pagarConSupervielle).mockResolvedValue({
      pago_id: 'spv1',
      url_pago: 'https://recaudaciones.test/publicacion/h1',
    })
    renderDeclaracion()

    vi.mocked(pagosApi.fetchPagosSupervielle).mockResolvedValue([PUBLICADO])
    fireEvent.click(await screen.findByRole('button', { name: 'Pagar con Supervielle' }))
    await waitFor(() => {
      expect(pestana.location.href).toBe('https://recaudaciones.test/publicacion/h1')
    })
    // La pestaña del banco no puede manejar la de la Suite.
    expect(pestana.opener).toBeNull()
    expect(pagosApi.pagarConSupervielle).toHaveBeenCalledWith('b1')

    // Sin pago informado todavía, se avisa y se puede volver a verificar.
    vi.mocked(pagosApi.sincronizarPagoSPV).mockResolvedValue(PUBLICADO)
    fireEvent.click(await screen.findByRole('button', { name: 'Ya pagué: verificar' }))
    expect(await screen.findByText(/El banco todavía no informa un pago/)).toBeInTheDocument()
    expect(pagosApi.sincronizarPagoSPV).toHaveBeenCalledWith('spv1')
    open.mockRestore()
  })

  it('si el banco no responde, cierra la pestaña y muestra el motivo', async () => {
    const pestana = { opener: {}, location: { href: '' }, close: vi.fn() }
    const open = vi.spyOn(window, 'open').mockReturnValue(pestana as unknown as Window)
    vi.mocked(pagosApi.pagarConSupervielle).mockRejectedValue(
      Object.assign(new Error('503'), {
        isAxiosError: true,
        response: {
          status: 503,
          data: {
            title: 'Service Unavailable',
            status: 503,
            detail: 'El botón no está disponible.',
          },
        },
      }),
    )
    renderDeclaracion()
    fireEvent.click(await screen.findByRole('button', { name: 'Pagar con Supervielle' }))
    await waitFor(() => {
      expect(pestana.close).toHaveBeenCalled()
    })
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    open.mockRestore()
  })

  it('no se ofrece si no está configurado ni para una boleta que vence hoy', async () => {
    vi.mocked(pagosApi.fetchSupervielleHabilitado).mockResolvedValue(false)
    const { unmount } = renderDeclaracion()
    expect(await screen.findByText('Boleta N° 1069')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pagar con Supervielle' })).not.toBeInTheDocument()
    unmount()

    vi.mocked(pagosApi.fetchSupervielleHabilitado).mockResolvedValue(true)
    const hoy = new Date().toLocaleDateString('en-CA', {
      timeZone: 'America/Argentina/San_Juan',
    })
    vi.mocked(ddjjApi.fetchDeclaracion).mockResolvedValue({
      ...DDJJ,
      boletas: [{ ...BOLETA, fecha_pago: hoy }],
    })
    renderDeclaracion()
    expect(await screen.findByText('Boleta N° 1069')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pagar con Supervielle' })).not.toBeInTheDocument()
  })

  it('un pago en proceso queda a la vista para volver a verificar', async () => {
    vi.mocked(pagosApi.fetchPagosSupervielle).mockResolvedValue([
      { ...PUBLICADO, estado: 'PENDIENTE', medio_pago: 'Caja en banco Supervielle' },
    ])
    renderDeclaracion()
    expect(await screen.findByText('Pago con Supervielle en proceso')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ya pagué: verificar' })).toBeInTheDocument()
  })
})
