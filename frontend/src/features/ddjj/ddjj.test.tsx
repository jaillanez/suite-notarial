import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as apiModule from './api'
import { DeclaracionPage } from './DeclaracionPage'
import { formatCodigo, formatPeriodo, periodoAnterior, rangoPeriodo } from './labels'
import { VerificarBoletaPage } from './VerificarBoletaPage'

vi.mock('./api')

const NOTARIO = {
  ...ESCRIBANO,
  permissions: ['ddjj:read_own', 'ddjj:create_own', 'boletas:read_own'],
}

const REGISTRO = {
  id: 'r1',
  numero_registro: 51,
  nombre_fantasia: null,
  departamento: 'Capital',
}

const ACTO: apiModule.Acto = {
  id: 'a1',
  escribano_id: 'e1',
  escribano: 'Sintético, Escribano',
  matricula_numero: 101,
  cargo: 'TITULAR',
  tipo_protocolo: 'GENERAL',
  numero_escritura: 101,
  orden_en_escritura: 1,
  motivo_exencion: null,
  detalle_exencion: null,
  folio: null,
  fecha_acto: '2026-09-15',
  naturaleza: 'Compraventa',
  categoria: 'ESCRITURA_CON_VALOR',
  base_imponible: '100000000.00',
  aporte: null,
  vigencia_id: null,
  vademecum_id: null,
  vademecum_nombre: null,
  fuera_de_vademecum: false,
  precio: null,
  avaluo: null,
  mismas_partes: true,
  aporte_individual: null,
}

const IMPORTES = {
  total_protocolos: '984699.06',
  aporte_minimo: '85932.00',
  excedente: '898767.06',
  aporte_medico: '97000.00',
  cantidad_aportes_medicos: 1,
  total_en_termino: '1081699.06',
  dias_mora: 0,
  interes_mora: '0.00',
  tramos_mora: [],
  total_a_pagar: '1081699.06',
}

const TITULAR: apiModule.EscribanoBoleta = {
  id: 'e1',
  apellido_nombre: 'SINTÉTICO, Escribano',
  cargo: 'TITULAR',
  modalidad: 'COMPLETA',
}

const ADSCRIPTO: apiModule.EscribanoBoleta = {
  id: 'e2',
  apellido_nombre: 'ADSCRIPTA, Prueba',
  cargo: 'ADSCRIPTO',
  modalidad: 'COMPLETA',
}

/** Liquidación con una boleta por escribano (por defecto, solo la del titular). */
function liquidacion(
  boletas: apiModule.LiquidacionBoleta[] = [{ ...IMPORTES, escribano: TITULAR }],
  extra: Partial<apiModule.Liquidacion> = {},
): apiModule.Liquidacion {
  return {
    aportes: [],
    vencimiento: '2026-10-28',
    fecha_pago: '2026-10-23',
    boletas,
    total_protocolos: '0.00',
    total_a_pagar: boletas.reduce((t, b) => t + Number(b.total_a_pagar), 0).toFixed(2),
    avisos: [],
    usa_valores_de_ejemplo: false,
    criterio_pluralidad: null,
    ...extra,
  }
}

const BOLETA: apiModule.Boleta = {
  ...IMPORTES,
  id: 'b1',
  numero: 1069,
  codigo_verificacion: 'ABCDEFGH23456723',
  ddjj_id: 'd1',
  registro: REGISTRO,
  escribano: TITULAR,
  puede_reemitir: true,
  periodo: '2026-09',
  numero_rectificativa: 0,
  estado: 'PENDIENTE',
  fecha_emision: '2026-10-23',
  fecha_vencimiento: '2026-10-28',
  fecha_pago: '2026-10-23',
  created_at: '2026-10-23T12:00:00Z',
  emitida_por: 'Caja Notarial',
  anulada_en: null,
  motivo_anulacion: null,
  comprobante: null,
}

const DDJJ: apiModule.DeclaracionDetalle = {
  id: 'd1',
  registro: REGISTRO,
  periodo: '2026-09',
  numero_rectificativa: 0,
  estado: 'BORRADOR',
  observaciones: null,
  fecha_presentacion: null,
  presentada_por: null,
  rectifica_a_id: null,
  cantidad_actos: 1,
  total_protocolos: null,
  vencimiento: '2026-10-28',
  created_at: '2026-10-01T12:00:00Z',
  actos: [ACTO],
  boletas: [],
  escribanos: [
    {
      id: 'e1',
      apellido_nombre: 'Sintético, Escribano',
      matricula_numero: 101,
      cargo: 'TITULAR',
    },
  ],
  puede_operar: true,
  controles: {},
  huecos: [],
  proximos_numeros: { GENERAL: 1, AUXILIAR: 1 },
}

function renderFicha() {
  return renderWithProviders(
    <Routes>
      <Route path="/ddjj/:id" element={<DeclaracionPage />} />
    </Routes>,
    { path: '/ddjj/d1', user: NOTARIO, raw: true },
  )
}

describe('etiquetas de DDJJ', () => {
  it('formatea y recorre períodos sin corrimientos de zona', () => {
    expect(formatPeriodo('2026-09')).toBe('09/2026')
    expect(periodoAnterior('2026-01')).toBe('2025-12')
    expect(rangoPeriodo('2028-02')).toEqual({ desde: '2028-02-01', hasta: '2028-02-29' })
    expect(formatCodigo('ABCDEFGH23456723')).toBe('ABCD EFGH 2345 6723')
  })
})

describe('ficha de la DDJJ', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(apiModule.verificarActo).mockResolvedValue({ aporte: null, controles: [] })
    vi.mocked(apiModule.fetchVademecum).mockResolvedValue([])
  })

  it('muestra la liquidación del borrador y avisa los valores a confirmar', async () => {
    vi.mocked(apiModule.fetchDeclaracion).mockResolvedValue(DDJJ)
    vi.mocked(apiModule.fetchLiquidacion).mockResolvedValue(
      liquidacion(undefined, {
        aportes: [
          {
            acto_id: 'a1',
            aporte: '400000.00',
            aporte_individual: '400000.00',
            incluido_en_otro: false,
          },
        ],
        usa_valores_de_ejemplo: true,
      }),
    )

    renderFicha()

    expect(await screen.findByText('Incluye valores a confirmar')).toBeInTheDocument()
    expect(screen.getAllByText('$ 1.081.699,06').length).toBeGreaterThan(0)
    expect(screen.getAllByText('$ 400.000,00').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Agregar acto' })).toBeInTheDocument()
  })

  it('avisa folios fuera de orden y números salteados del año', async () => {
    vi.mocked(apiModule.fetchDeclaracion).mockResolvedValue({
      ...DDJJ,
      controles: {
        a1: [
          {
            codigo: 'FOLIO_FUERA_DE_ORDEN',
            nivel: 'ADVERTENCIA',
            mensaje: 'El folio 30 no sigue el orden de la numeración.',
          },
        ],
      },
      huecos: [
        {
          tipo_protocolo: 'GENERAL',
          tramos: [
            { desde: 21, hasta: 22 },
            { desde: 30, hasta: 41 },
          ],
          total: 14,
        },
      ],
    })
    vi.mocked(apiModule.fetchLiquidacion).mockResolvedValue(
      liquidacion(undefined, {
        aportes: [
          {
            acto_id: 'a1',
            aporte: '400000.00',
            aporte_individual: '400000.00',
            incluido_en_otro: false,
          },
        ],
      }),
    )

    renderFicha()

    expect(
      await screen.findByText('Hay números de escritura sin declarar este año'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Protocolo general: 21, 22 y 30 a 41 \(14 números\)/),
    ).toBeInTheDocument()
    expect(
      screen.getAllByText('El folio 30 no sigue el orden de la numeración.').length,
    ).toBeGreaterThan(0)
  })

  it('detalla el interés por tramos cuando la tasa cambió durante el atraso', async () => {
    vi.mocked(apiModule.fetchDeclaracion).mockResolvedValue(DDJJ)
    vi.mocked(apiModule.fetchLiquidacion).mockResolvedValue(
      liquidacion([
        {
          ...IMPORTES,
          escribano: TITULAR,
          dias_mora: 10,
          interes_mora: '16676.19',
          tramos_mora: [
            {
              desde: '2026-10-29',
              hasta: '2026-11-02',
              dias: 5,
              tasa: '4.2500',
              periodo_tasa: 'MENSUAL',
              interes: '7662.04',
            },
            {
              desde: '2026-11-03',
              hasta: '2026-11-07',
              dias: 5,
              tasa: '5.0000',
              periodo_tasa: 'MENSUAL',
              interes: '9014.15',
            },
          ],
          total_a_pagar: '1098375.25',
        },
      ]),
    )

    renderFicha()

    expect(await screen.findByText('La tasa cambió durante el atraso:')).toBeInTheDocument()
    expect(
      screen.getByText(/Del 29\/10\/2026 al 02\/11\/2026: 5 días al 4,25 % mensual/),
    ).toBeInTheDocument()
    expect(screen.getByText('$ 9.014,15')).toBeInTheDocument()
  })

  it('el alta muestra el aporte en vivo y no deja agregar un número repetido', async () => {
    vi.mocked(apiModule.fetchDeclaracion).mockResolvedValue(DDJJ)
    vi.mocked(apiModule.fetchLiquidacion).mockResolvedValue(liquidacion())
    vi.mocked(apiModule.verificarActo).mockResolvedValue({
      aporte: '21600.00',
      controles: [
        {
          codigo: 'NUMERO_REPETIDO',
          nivel: 'BLOQUEANTE',
          mensaje:
            'La escritura N° 101 del protocolo general ya está declarada en la DDJJ 08/2026.',
        },
      ],
    })

    renderFicha()
    fireEvent.click(await screen.findByRole('button', { name: 'Agregar acto' }))
    fireEvent.change(screen.getByLabelText('N° de escritura'), { target: { value: '101' } })
    fireEvent.change(screen.getByLabelText('Naturaleza del acto'), {
      target: { value: 'Compraventa' },
    })
    fireEvent.change(screen.getByLabelText('Base imponible ($)'), {
      target: { value: '1.000.000' },
    })

    expect(await screen.findByText('$ 21.600,00')).toBeInTheDocument()
    expect(screen.getByText(/ya está declarada en la DDJJ 08\/2026/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Agregar' })).toBeDisabled()
  })

  it('carga rápida: viene completado con el último acto y sigue con el próximo número', async () => {
    vi.mocked(apiModule.fetchDeclaracion).mockResolvedValue({
      ...DDJJ,
      proximos_numeros: { GENERAL: 102, AUXILIAR: 1 },
    })
    vi.mocked(apiModule.fetchLiquidacion).mockResolvedValue(liquidacion())
    vi.mocked(apiModule.verificarActo).mockResolvedValue({ aporte: '21600.00', controles: [] })
    vi.mocked(apiModule.agregarActo).mockResolvedValue({ ...ACTO, id: 'a2', numero_escritura: 102 })

    renderFicha()
    fireEvent.click(await screen.findByRole('button', { name: 'Agregar acto' }))
    // Número que sigue y la fecha del último acto, sin tipear.
    expect(screen.getByLabelText('N° de escritura')).toHaveValue('102')
    expect(screen.getByLabelText('Fecha del acto')).toHaveValue('2026-09-15')
    fireEvent.change(screen.getByLabelText('Naturaleza del acto'), {
      target: { value: 'Hipoteca' },
    })
    fireEvent.change(screen.getByLabelText('Base imponible ($)'), {
      target: { value: '1.000.000' },
    })
    const otro = screen.getByRole('button', { name: 'Agregar y cargar otro' })
    await waitFor(() => {
      expect(otro).toBeEnabled()
    })
    fireEvent.click(otro)

    expect(await screen.findByText(/Escritura N° 102 agregada/)).toBeInTheDocument()
    expect(apiModule.agregarActo).toHaveBeenCalledWith(
      'd1',
      expect.objectContaining({ numero_escritura: 102, fecha_acto: '2026-09-15' }),
    )
    // Sigue abierto, con el número siguiente y los campos del acto en blanco.
    expect(screen.getByLabelText('N° de escritura')).toHaveValue('103')
    expect(screen.getByLabelText('Naturaleza del acto')).toHaveValue('')
    expect(screen.getByLabelText('Fecha del acto')).toHaveValue('2026-09-15')
  })

  it('liquida una boleta por escribano y avisa lo que hay que revisar', async () => {
    vi.mocked(apiModule.fetchDeclaracion).mockResolvedValue(DDJJ)
    vi.mocked(apiModule.fetchLiquidacion).mockResolvedValue(
      liquidacion(
        [
          { ...IMPORTES, escribano: TITULAR },
          {
            ...IMPORTES,
            escribano: ADSCRIPTO,
            total_protocolos: '0.00',
            excedente: '0.00',
            total_en_termino: '182932.00',
            total_a_pagar: '182932.00',
          },
          {
            ...IMPORTES,
            escribano: {
              id: 'e3',
              apellido_nombre: 'DESIGNADO, Interino',
              cargo: 'SUPLENTE_INTERINO',
              modalidad: 'SOLO_ACTOS',
            },
            total_protocolos: '400000.00',
            aporte_minimo: '0.00',
            excedente: '400000.00',
            aporte_medico: '0.00',
            cantidad_aportes_medicos: 0,
            total_en_termino: '400000.00',
            total_a_pagar: '400000.00',
          },
        ],
        {
          avisos: [
            'ADSCRIPTA, Prueba termina su cargo dentro del período: se cobra el mínimo mensual completo (la Caja todavía no definió un proporcional).',
          ],
        },
      ),
    )

    renderFicha()

    const adscripta = await screen.findByRole('region', { name: 'Boleta de ADSCRIPTA, Prueba' })
    expect(within(adscripta).getByText('Adscripto')).toBeInTheDocument()
    expect(within(adscripta).getAllByText('$ 182.932,00').length).toBeGreaterThan(0)
    // Quien está a cargo solo por sus actos: sin mínimo ni aporte médico.
    const aCargo = screen.getByRole('region', { name: 'Boleta de DESIGNADO, Interino' })
    expect(within(aCargo).getByText('A cargo · solo el aporte de sus actos')).toBeInTheDocument()
    expect(within(aCargo).getByText('Aporte de sus actos')).toBeInTheDocument()
    expect(within(aCargo).queryByText('Aporte médico asistencial')).not.toBeInTheDocument()
    expect(within(aCargo).queryByText('Aporte mínimo')).not.toBeInTheDocument()
    // Total del registro: la suma de las tres.
    expect(screen.getByText(/3 boletas, cada escribano paga la suya/)).toBeInTheDocument()
    expect(screen.getByText('$ 1.664.631,06')).toBeInTheDocument()
    expect(screen.getByText(/termina su cargo dentro del período/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Presentar y emitir boletas' })).toBeInTheDocument()
  })

  it('cada escribano reemite su propia boleta', async () => {
    const adscripta: apiModule.Boleta = {
      ...BOLETA,
      id: 'b2',
      numero: 1070,
      codigo_verificacion: 'ZYXWVUTS23456723',
      escribano: ADSCRIPTO,
      total_a_pagar: '182932.00',
    }
    const otro: apiModule.Boleta = {
      ...BOLETA,
      id: 'b4',
      numero: 1072,
      escribano: { ...ADSCRIPTO, id: 'e3', apellido_nombre: 'AJENO, Colega' },
      puede_reemitir: false,
    }
    vi.mocked(apiModule.fetchDeclaracion).mockResolvedValue({
      ...DDJJ,
      estado: 'PRESENTADA',
      actos: [{ ...ACTO, aporte: '400000.00', vigencia_id: 'v1' }],
      boletas: [otro, adscripta, { ...BOLETA, estado: 'PAGADA' }],
    })
    vi.mocked(apiModule.emitirBoleta).mockResolvedValue({ ...adscripta, id: 'b3', numero: 1071 })

    renderFicha()

    // Titular primero aunque su boleta sea más vieja; ya pagó: no se le ofrece otra.
    const grupos = await screen.findAllByRole('region', { name: /^Boletas de / })
    expect(grupos.map((g) => g.getAttribute('aria-label'))).toEqual([
      'Boletas de SINTÉTICO, Escribano',
      'Boletas de AJENO, Colega',
      'Boletas de ADSCRIPTA, Prueba',
    ])
    // La de otro escribano no se reemite desde esta sesión (anularía su pendiente).
    expect(
      within(grupos[1] as HTMLElement).queryByRole('button', { name: 'Nueva boleta' }),
    ).toBeNull()
    expect(
      within(grupos[0] as HTMLElement).queryByRole('button', { name: 'Nueva boleta' }),
    ).toBeNull()
    fireEvent.click(within(grupos[2] as HTMLElement).getByRole('button', { name: 'Nueva boleta' }))
    expect(await screen.findByText('Nueva boleta de ADSCRIPTA, Prueba')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Emitir boleta' }))

    await waitFor(() => {
      expect(apiModule.emitirBoleta).toHaveBeenCalledWith('d1', expect.any(String), 'e2')
    })
  })

  it('una DDJJ presentada no se edita: ofrece rectificar y descargar la boleta', async () => {
    vi.mocked(apiModule.fetchDeclaracion).mockResolvedValue({
      ...DDJJ,
      estado: 'PRESENTADA',
      fecha_presentacion: '2026-10-23T12:00:00Z',
      presentada_por: 'Caja Notarial',
      actos: [{ ...ACTO, aporte: '400000.00', vigencia_id: 'v1' }],
      boletas: [BOLETA],
    })

    renderFicha()

    expect(await screen.findByText('Liquidación presentada')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Agregar acto' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rectificar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Descargar PDF' })).toBeInTheDocument()
    expect(screen.getByText('Pendiente de pago')).toBeInTheDocument()
    expect(apiModule.fetchLiquidacion).not.toHaveBeenCalled()
  })
})

describe('verificación pública', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  const VERIFICACION: apiModule.Verificacion = {
    numero: 1069,
    codigo_verificacion: 'ABCDEFGH23456723',
    registro_numero: 51,
    periodo: '2026-09',
    estado: 'PENDIENTE',
    fecha_emision: '2026-10-23',
    fecha_pago: '2026-10-23',
    total_a_pagar: '1081699.06',
    integra: true,
  }

  function renderVerificar(codigo: string) {
    return renderWithProviders(
      <Routes>
        <Route path="/verificar/:codigo" element={<VerificarBoletaPage />} />
      </Routes>,
      { path: `/verificar/${codigo}`, raw: true },
    )
  }

  it('confirma una boleta auténtica (acepta el código en minúsculas)', async () => {
    vi.mocked(apiModule.verificarBoleta).mockResolvedValue(VERIFICACION)

    renderVerificar('abcdefgh23456723')

    expect(await screen.findByText('Boleta auténtica')).toBeInTheDocument()
    expect(screen.getByText('$ 1.081.699,06')).toBeInTheDocument()
    expect(apiModule.verificarBoleta).toHaveBeenCalledWith('ABCDEFGH23456723')
  })

  it('alerta si la boleta no supera el control de integridad', async () => {
    vi.mocked(apiModule.verificarBoleta).mockResolvedValue({ ...VERIFICACION, integra: false })

    renderVerificar('ABCDEFGH23456723')

    expect(await screen.findByText('Los datos de la boleta no coinciden')).toBeInTheDocument()
  })
})

const VADEMECUM_BASE = {
  version: 1,
  motivo_exencion: null,
  aclaracion: null,
  fecha_desde: '2026-06-01',
  fecha_hasta: null,
  resolucion: 'Vademécum de aportes · Asamblea Extraordinaria del 19/05/2026',
  estado: 'VIGENTE',
  created_by_user_id: 'u-autor',
  aprobado_por_user_id: 'u-revisor',
  created_at: '2026-06-01T12:00:00Z',
} as const

const VADEMECUM: apiModule.VademecumActo[] = [
  {
    ...VADEMECUM_BASE,
    id: 'v-venta',
    codigo: 'VENTA',
    nombre: 'Venta',
    categoria: 'ESCRITURA_CON_VALOR',
    sinonimos: 'compraventa',
    orden: 101,
  },
  {
    ...VADEMECUM_BASE,
    id: 'v-cesion',
    codigo: 'CESION',
    nombre: 'Cesión',
    categoria: 'OTRO_ACTO',
    sinonimos: 'cesión de derechos',
    aclaracion: 'Las cesiones onerosas sobre un inmueble determinado son aporte variable.',
    orden: 202,
  },
  {
    ...VADEMECUM_BASE,
    id: 'v-ipv',
    codigo: 'IPV',
    nombre: 'Hipoteca, cancelación de hipoteca, poder o venta del IPV',
    categoria: 'EXENTO',
    motivo_exencion: 'CONVENIO_IPV',
    sinonimos: 'instituto provincial de la vivienda',
    orden: 402,
  },
]

describe('vademécum de aportes', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(apiModule.verificarActo).mockResolvedValue({ aporte: null, controles: [] })
    vi.mocked(apiModule.fetchVademecum).mockResolvedValue(VADEMECUM)
    vi.mocked(apiModule.fetchDeclaracion).mockResolvedValue({ ...DDJJ, actos: [] })
    vi.mocked(apiModule.fetchLiquidacion).mockResolvedValue(liquidacion())
  })

  it('busca sin tildes y por sinónimos, y el acto fija cómo aporta', async () => {
    vi.mocked(apiModule.agregarActo).mockResolvedValue(ACTO)
    renderFicha()
    fireEvent.click(await screen.findByRole('button', { name: 'Agregar acto' }))
    const dialogo = await screen.findByRole('dialog')
    const buscador = await within(dialogo).findByRole('combobox', {
      name: 'Acto (vademécum de aportes)',
    })
    // Sin el selector de tipo: lo define el acto.
    expect(within(dialogo).queryByLabelText('Tipo de acto')).not.toBeInTheDocument()

    fireEvent.change(buscador, { target: { value: 'cesion' } })
    expect(within(dialogo).getByRole('option', { name: 'Cesión' })).toBeInTheDocument()
    expect(within(dialogo).queryByRole('option', { name: 'Venta' })).not.toBeInTheDocument()

    fireEvent.change(buscador, { target: { value: 'compraventa' } })
    fireEvent.keyDown(buscador, { key: 'Enter' })
    expect(buscador).toHaveValue('Venta')
    expect(within(dialogo).getByText(/Aporte variable\./)).toBeInTheDocument()
    expect(within(dialogo).getByLabelText('Naturaleza del acto')).toHaveValue('Venta')

    fireEvent.change(within(dialogo).getByLabelText('Precio ($)'), {
      target: { value: '1.000.000,00' },
    })
    fireEvent.change(within(dialogo).getByLabelText('Avalúo ($)'), {
      target: { value: '1.250.000' },
    })
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Agregar' }))

    await waitFor(() => {
      expect(apiModule.agregarActo).toHaveBeenCalledWith(
        'd1',
        expect.objectContaining({
          vademecum_id: 'v-venta',
          categoria: 'ESCRITURA_CON_VALOR',
          naturaleza: 'Venta',
          precio: '1000000.00',
          avaluo: '1250000',
          base_imponible: '0',
          mismas_partes: null,
        }),
      )
    })
  })

  it('un acto que no está en el vademécum elige cómo aporta', async () => {
    renderFicha()
    fireEvent.click(await screen.findByRole('button', { name: 'Agregar acto' }))
    const dialogo = await screen.findByRole('dialog')
    const buscador = await within(dialogo).findByRole('combobox', {
      name: 'Acto (vademécum de aportes)',
    })
    const agregar = within(dialogo).getByRole('button', { name: 'Agregar' })
    fireEvent.change(within(dialogo).getByLabelText('Naturaleza del acto'), {
      target: { value: 'Acto raro' },
    })
    // Sin elegir en el buscador no se puede agregar.
    expect(agregar).toBeDisabled()

    fireEvent.change(buscador, { target: { value: 'zzz' } })
    expect(within(dialogo).getByText(/Ningún acto coincide/)).toBeInTheDocument()
    fireEvent.click(within(dialogo).getByRole('option', { name: 'No está en el vademécum' }))
    expect(within(dialogo).getByLabelText('Cómo aporta')).toBeInTheDocument()
    expect(within(dialogo).getByText(/la Caja lo revise/)).toBeInTheDocument()
  })

  it('pregunta por las partes en un acto de la misma escritura', async () => {
    renderFicha()
    fireEvent.click(await screen.findByRole('button', { name: 'Agregar acto' }))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.click(within(dialogo).getByLabelText(/Otro acto de la misma escritura/))
    const grupo = within(dialogo).getByRole('group', {
      name: /Intervienen solo las mismas partes/,
    })
    // Sin respuesta por defecto: hay que elegir.
    expect(within(grupo).getByLabelText(/Sí, las mismas partes/)).not.toBeChecked()
    expect(within(grupo).getByLabelText(/No, hay partes distintas/)).not.toBeChecked()
    fireEvent.click(within(grupo).getByLabelText(/No, hay partes distintas/))
    expect(within(grupo).getByLabelText(/No, hay partes distintas/)).toBeChecked()
  })

  it('muestra el acto incluido en el principal y la regla que se aplicó', async () => {
    const donacion = {
      ...ACTO,
      id: 'a2',
      orden_en_escritura: 2,
      naturaleza: 'Donación',
      categoria: 'OTRO_ACTO' as const,
      base_imponible: '0.00',
      fuera_de_vademecum: true,
    }
    vi.mocked(apiModule.fetchDeclaracion).mockResolvedValue({ ...DDJJ, actos: [ACTO, donacion] })
    vi.mocked(apiModule.fetchLiquidacion).mockResolvedValue(
      liquidacion(undefined, {
        aportes: [
          {
            acto_id: 'a1',
            aporte: '400000.00',
            aporte_individual: '400000.00',
            incluido_en_otro: false,
          },
          { acto_id: 'a2', aporte: '0.00', aporte_individual: '37446.00', incluido_en_otro: true },
        ],
        criterio_pluralidad: 'SOLO_EL_MAYOR',
      }),
    )
    renderFicha()

    expect(
      await screen.findByText('Escrituras con varios actos y las mismas partes'),
    ).toBeInTheDocument()
    expect(screen.getAllByText('Incluido en el acto principal').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Solo: \$ 37\.446,00/).length).toBeGreaterThan(0)
    expect(
      screen.getAllByText('No está en el vademécum: lo revisa la Caja').length,
    ).toBeGreaterThan(0)
  })
})
