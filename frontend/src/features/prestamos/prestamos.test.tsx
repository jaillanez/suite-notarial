import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as apiModule from './api'
import { PlanCuotas, ResumenEvaluacion } from './componentes'
import { importe, requisitosLinea, textoMeses } from './labels'
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
  moneda: 'ARS',
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
  avisos: [],
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

  it('en dólares muestra US$ y los avisos que no impiden otorgar', () => {
    renderWithProviders(
      <ResumenEvaluacion
        ev={{
          ...EV,
          moneda: 'USD',
          tasa_es_ejemplo: false,
          impedimentos: [],
          cuota_maxima: '990.06',
          totales: { capital: '50000.00', intereses: '9403.60', total: '59403.60' },
          avisos: ['Antigüedad no verificable: falta la fecha de matriculación.'],
        }}
        conIngreso
      />,
    )

    expect(screen.getByText('US$ 990,06')).toBeInTheDocument()
    expect(screen.getByText('US$ 59.403,60')).toBeInTheDocument()
    expect(screen.getByText('Dólares estadounidenses')).toBeInTheDocument()
    expect(screen.getByText('Para revisar')).toBeInTheDocument()
    expect(screen.getByText(/Antigüedad no verificable/)).toBeInTheDocument()
    expect(screen.queryByText(/^\$ /)).not.toBeInTheDocument()
  })

  it('el cuadro de amortización usa la moneda del préstamo', () => {
    renderWithProviders(
      <PlanCuotas plan={[CUOTA]} totales={EV.totales} conEstado={false} moneda="USD" />,
    )
    expect(screen.getAllByText('US$ 8.884,88').length).toBeGreaterThan(0)
  })
})

describe('líneas', () => {
  const LINEA: apiModule.Linea = {
    id: 'l1',
    codigo: 'HIPOTECARIO_USD',
    nombre: 'Hipotecario en dólares',
    descripcion: null,
    sistema: 'FRANCES',
    plazo_minimo: 1,
    plazo_maximo: 60,
    monto_minimo: '0.01',
    monto_maximo: '50000.00',
    tna: '7.0000',
    afectacion_maxima: '30.0000',
    requiere_garante: false,
    moneda: 'USD',
    garantia: 'Hipoteca.',
    requisito_conducta: 'Conducta regular en el último año.',
    relacion_capital_hipoteca: '70.0000',
    requiere_certificado_ingresos: true,
    requiere_certificado_bienes: true,
    antiguedad_minima_meses: 12,
    es_ejemplo: false,
    is_active: true,
  }

  it('describe los requisitos en frases cortas', () => {
    expect(requisitosLinea(LINEA)).toEqual([
      'Garantía: Hipoteca',
      'Capital hasta el 70 % del valor del inmueble hipotecado',
      'Certificado de ingresos',
      'Certificado de bienes y deudas',
      'Antigüedad en la matrícula: 1 año',
      'Conducta regular en el último año',
    ])
    expect(
      requisitosLinea({
        ...LINEA,
        garantia: null,
        requisito_conducta: null,
        relacion_capital_hipoteca: null,
        requiere_certificado_ingresos: false,
        requiere_certificado_bienes: false,
        antiguedad_minima_meses: null,
        requiere_garante: true,
      }),
    ).toEqual(['Garante solidario matriculado'])
  })

  it('formatea importes por moneda y plazos en meses o años', () => {
    expect(importe('50000', 'USD')).toBe('US$ 50.000,00')
    expect(importe('-1500.5', 'ARS')).toBe('−$ 1.500,50')
    expect(importe(null, 'USD')).toBe('—')
    expect(textoMeses(12)).toBe('1 año')
    expect(textoMeses(36)).toBe('3 años')
    expect(textoMeses(1)).toBe('1 mes')
    expect(textoMeses(18)).toBe('18 meses')
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
    moneda: 'ARS',
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
    avisos_actuales: [],
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

  it('un préstamo en dólares muestra US$ y los avisos para quien resuelve', async () => {
    vi.mocked(apiModule.fetchPrestamo).mockResolvedValue({
      ...BASE,
      moneda: 'USD',
      capital: '50000.00',
      ingreso_neto: '3301.00',
      avisos_actuales: ['Antigüedad no verificable: falta la fecha de matriculación.'],
    })
    renderFicha(['prestamos:read_all', 'prestamos:approve'])

    expect(await screen.findByText('US$ 50.000,00')).toBeInTheDocument()
    expect(screen.getByText('US$ 3.301,00')).toBeInTheDocument()
    expect(screen.getByText('Dólares estadounidenses')).toBeInTheDocument()
    expect(screen.getByText('Para revisar antes de resolver')).toBeInTheDocument()
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
