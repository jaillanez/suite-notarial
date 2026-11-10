import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as apiModule from './api'
import { PlanCuotas, ResumenEvaluacion } from './componentes'
import { importe, requisitosLinea, textoMeses } from './labels'
import { PrestamoPage } from './PrestamoPage'
import { PrestamosPage } from './PrestamosPage'

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

const SIN_SALDO: apiModule.SaldoConjunto = {
  escribano: null,
  monedas: [],
  solicitudes_pendientes: 0,
}
const SALDO: apiModule.SaldoConjunto = {
  escribano: { id: 'e1', apellido_nombre: 'Sintético, Escribano', matricula_numero: 101 },
  monedas: [
    {
      moneda: 'ARS',
      prestamos_vigentes: 2,
      saldo_capital: '192115.12',
      cuotas_pendientes: 23,
      total_pendiente: '204352.18',
      cuotas_vencidas: 1,
      importe_vencido: '8884.88',
      proximo_vencimiento: '2026-11-23',
      importe_proximo_vencimiento: '8884.88',
    },
  ],
  solicitudes_pendientes: 1,
}

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
    cobros_mp: [],
    puede_pagar_mp: false,
    documentos: [],
    documentacion_requerida: [],
    puede_cargar_documentos: false,
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
    vi.mocked(apiModule.fetchSaldo).mockResolvedValue(SIN_SALDO)
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
  const OTORGADO: apiModule.PrestamoDetalle = {
    ...BASE,
    estado: 'OTORGADO',
    fecha_otorgamiento: '2026-10-23',
    plan: [{ ...CUOTA, vencida: false }],
  }
  const COBRO: apiModule.CobroCuotaMP = {
    id: 'mp1',
    cuota: 1,
    estado: 'approved',
    medio_pago: 'account_money',
    importe_pagado: '8884.88',
    aprobado_en: '2026-10-23T13:15:00Z',
    confirmado_en: null,
    a_confirmar: true,
  }

  it('el escribano paga la próxima cuota con Mercado Pago', async () => {
    vi.mocked(apiModule.fetchPrestamo).mockResolvedValue({ ...OTORGADO, puede_pagar_mp: true })
    vi.mocked(apiModule.pagarCuotaConMercadoPago).mockResolvedValue('https://mp.test/checkout/1')
    const assign = vi.fn()
    vi.stubGlobal('location', {
      assign,
      href: window.location.href,
      origin: window.location.origin,
      pathname: window.location.pathname,
      search: window.location.search,
      hash: window.location.hash,
    })
    renderFicha(['prestamos:read_own'])

    fireEvent.click(await screen.findByRole('button', { name: 'Pagar cuota 1 con Mercado Pago' }))
    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith('https://mp.test/checkout/1')
    })
    expect(apiModule.pagarCuotaConMercadoPago).toHaveBeenCalledWith('p1')
    vi.unstubAllGlobals()
  })

  it('con el pago aprobado, el escribano espera a Tesorería y no puede volver a pagar', async () => {
    vi.mocked(apiModule.fetchPrestamo).mockResolvedValue({ ...OTORGADO, cobros_mp: [COBRO] })
    renderFicha(['prestamos:read_own'])

    expect(await screen.findByText('Pagaste la cuota 1 con Mercado Pago')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Mercado Pago/ })).not.toBeInTheDocument()
    expect(screen.getByText('Aprobado · a confirmar')).toBeInTheDocument()
  })

  it('Tesorería confirma el cobro en lugar de registrarlo a mano', async () => {
    vi.mocked(apiModule.fetchPrestamo).mockResolvedValue({ ...OTORGADO, cobros_mp: [COBRO] })
    vi.mocked(apiModule.confirmarCobroMP).mockResolvedValue(OTORGADO)
    renderFicha(['prestamos:read_all', 'prestamos:cobrar'])

    fireEvent.click(await screen.findByRole('button', { name: 'Confirmar cobro de la cuota 1' }))
    expect(
      screen.queryByRole('button', { name: 'Registrar pago de la cuota 1' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/no coincide con la cuota/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar cobro' }))
    await waitFor(() => {
      expect(apiModule.confirmarCobroMP).toHaveBeenCalledWith('p1', 'mp1')
    })
  })

  const DOC: apiModule.DocumentoPrestamo = {
    id: 'd1',
    tipo: 'CERTIFICADO_INGRESOS',
    descripcion: null,
    nombre_original: 'ingresos.pdf',
    mime_type: 'application/pdf',
    tamano_bytes: 2048,
    subido_por: 'Vos',
    created_at: '2026-10-23T13:00:00Z',
    anulado_en: null,
    motivo_anulacion: null,
    puede_anular: true,
  }

  it('muestra lo que exige la línea y carga el documento que falta', async () => {
    const pendiente = {
      ...BASE,
      impedimentos_actuales: ['Falta cargar el certificado de bienes y deudas.'],
      documentos: [DOC],
      documentacion_requerida: [
        { tipo: 'CERTIFICADO_INGRESOS' as const, cargado: true },
        { tipo: 'CERTIFICADO_BIENES' as const, cargado: false },
      ],
      puede_cargar_documentos: true,
    }
    vi.mocked(apiModule.fetchPrestamo).mockResolvedValue(pendiente)
    vi.mocked(apiModule.cargarDocumento).mockResolvedValue(pendiente)
    renderFicha(['prestamos:read_own'])

    expect(
      await screen.findByText(/sin ellos la solicitud no se puede otorgar/),
    ).toBeInTheDocument()
    expect(screen.getByText(': falta')).toBeInTheDocument()
    expect(screen.getByText(/ingresos\.pdf · 2 KB · Vos/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Agregar documento' }))
    // Propone lo que falta.
    expect(screen.getByRole('combobox', { name: 'Documento' })).toHaveValue('CERTIFICADO_BIENES')
    const cargar = screen.getByRole('button', { name: 'Cargar documento' })
    expect(cargar).toBeDisabled()
    const archivo = new File(['%PDF-1.4'], 'bienes.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByLabelText('Archivo'), { target: { files: [archivo] } })
    fireEvent.click(cargar)
    await waitFor(() => {
      expect(apiModule.cargarDocumento).toHaveBeenCalledWith('p1', {
        tipo: 'CERTIFICADO_BIENES',
        descripcion: '',
        archivo,
      })
    })
  })

  it('anular pide el motivo; el anulado queda a la vista', async () => {
    vi.mocked(apiModule.fetchPrestamo).mockResolvedValue({
      ...BASE,
      documentos: [
        DOC,
        {
          ...DOC,
          id: 'd2',
          tipo: 'OTRO',
          descripcion: 'Recibo de sueldo',
          anulado_en: '2026-10-23T14:00:00Z',
          motivo_anulacion: 'Archivo equivocado',
          puede_anular: false,
        },
      ],
      puede_cargar_documentos: true,
    })
    vi.mocked(apiModule.anularDocumento).mockResolvedValue(BASE)
    renderFicha(['prestamos:read_own'])

    expect(await screen.findByText('Anulado: Archivo equivocado')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Anular' })).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Anular' }))
    const confirmar = screen.getByRole('button', { name: 'Anular documento' })
    expect(confirmar).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Motivo/), { target: { value: 'No es el último' } })
    fireEvent.click(confirmar)
    await waitFor(() => {
      expect(apiModule.anularDocumento).toHaveBeenCalledWith('p1', 'd1', 'No es el último')
    })
  })

  it('el personal ve todo lo que el escribano debe en préstamos', async () => {
    vi.mocked(apiModule.fetchPrestamo).mockResolvedValue(BASE)
    vi.mocked(apiModule.fetchSaldo).mockResolvedValue(SALDO)
    renderFicha(['prestamos:read_all'])

    expect(
      await screen.findByText('Todos los préstamos de Sintético, Escribano'),
    ).toBeInTheDocument()
    expect(apiModule.fetchSaldo).toHaveBeenCalledWith('e1')
    expect(screen.getByText('$ 192.115,12')).toBeInTheDocument()
    expect(screen.getByText(/1 solicitud pendiente/)).toBeInTheDocument()
    // Sin documentación exigida ni cargada y sin poder cargar, no hay panel.
    expect(screen.queryByText('Documentación')).not.toBeInTheDocument()
  })
})

describe('mis préstamos', () => {
  it('el escribano ve el saldo del conjunto de sus préstamos', async () => {
    vi.resetAllMocks()
    vi.mocked(apiModule.fetchPrestamos).mockResolvedValue([])
    vi.mocked(apiModule.fetchSaldo).mockResolvedValue(SALDO)
    renderWithProviders(<PrestamosPage />, {
      user: { ...ESCRIBANO, permissions: ['prestamos:read_own'] },
    })

    expect(await screen.findByText('Saldo de tus préstamos')).toBeInTheDocument()
    expect(apiModule.fetchSaldo).toHaveBeenCalledWith()
    expect(screen.getByText('$ 204.352,18')).toBeInTheDocument()
    expect(screen.getByText('2 préstamos vigentes')).toBeInTheDocument()
    expect(screen.getByText('23/11/2026')).toBeInTheDocument()
    expect(screen.getAllByText('$ 8.884,88')).toHaveLength(2)
  })
})
