import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as ddjjApi from '../ddjj/api'
import * as padronApi from '../padron/api'
import { EscribanoNuevoPage } from '../padron/EscribanoNuevoPage'
import * as iaApi from './api'
import { confianzaPct, nivelConfianza } from './labels'
import { MinutaPage } from './MinutaPage'

vi.mock('./api')
vi.mock('../ddjj/api')
vi.mock('../padron/api')

const NOTARIO = { ...ESCRIBANO, permissions: ['ddjj:read_own', 'ddjj:create_own'] }

const DDJJ: ddjjApi.DeclaracionDetalle = {
  id: 'd1',
  registro: { id: 'r1', numero_registro: 51, nombre_fantasia: null, departamento: 'Capital' },
  periodo: '2026-09',
  numero_rectificativa: 0,
  estado: 'BORRADOR',
  observaciones: null,
  fecha_presentacion: null,
  presentada_por: null,
  rectifica_a_id: null,
  cantidad_actos: 0,
  total_protocolos: null,
  vencimiento: '2026-10-28',
  created_at: '2026-10-01T12:00:00Z',
  actos: [],
  boletas: [],
  escribanos: [
    { id: 'e1', apellido_nombre: 'Sintético, Titular', matricula_numero: 101, cargo: 'TITULAR' },
    {
      id: 'e2',
      apellido_nombre: 'Prueba, A Cargo',
      matricula_numero: 102,
      cargo: 'SUPLENTE_INTERINO',
    },
  ],
  puede_operar: true,
  controles: {},
  huecos: [],
}

const campo = (valor: string | null, confianza = '0.9000', evidencia: string | null = null) => ({
  valor,
  confianza,
  regla: 'Regla aplicada.',
  evidencia,
})

const SUGERENCIA: iaApi.Sugerencia = {
  id: 's1',
  tipo: 'EXTRACCION_MINUTA',
  estado: 'SUGERIDO_POR_IA',
  motor: 'reglas-minuta',
  motor_version: '1.0',
  confianza: '0.8188',
  tiempo_ms: 12,
  entrada: { origen: 'texto', mime_type: null, caracteres: 480, paginas: null, ocr: null },
  campos: {
    escribano_id: campo('e1'),
    tipo_protocolo: campo('GENERAL', '0.6000'),
    numero_escritura: campo('120', '0.9500'),
    folio: campo('345', '0.8500'),
    fecha_acto: campo('2026-09-14', '0.8500'),
    naturaleza: campo('Compraventa', '0.8000'),
    categoria: campo('ESCRITURA_CON_VALOR', '0.7000'),
    base_imponible: campo(
      '45000000.00',
      '0.3500',
      '…precio de PESOS CUARENTA MILLONES ($ 45.000.000,00)…',
    ),
  },
  alertas: [
    {
      codigo: 'MONTO_LETRAS_DISTINTO',
      nivel: 'ADVERTENCIA',
      mensaje: 'El monto en cifras no coincide con el escrito en letras.',
      evidencia: null,
    },
  ],
  ddjj_id: 'd1',
  campos_modificados: null,
  acto_id: null,
  escribano_id: null,
  resuelto_en: null,
  created_at: '2026-10-23T12:00:00Z',
}

describe('confianza', () => {
  it('se expresa en porcentaje entero y nivel, sin flotantes en el texto', () => {
    expect(confianzaPct('0.9500')).toBe(95)
    expect(confianzaPct('1.0000')).toBe(100)
    expect(confianzaPct('0.4')).toBe(40)
    expect(nivelConfianza('0.8500')).toBe('alta')
    expect(nivelConfianza('0.6000')).toBe('media')
    expect(nivelConfianza('0.3500')).toBe('baja')
  })
})

describe('carga desde la minuta (Human in Command)', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(ddjjApi.fetchDeclaracion).mockResolvedValue(DDJJ)
    vi.mocked(ddjjApi.verificarActo).mockResolvedValue({ aporte: '972000.00', controles: [] })
    vi.mocked(iaApi.fetchEstadoIa).mockResolvedValue({
      ocr_disponible: true,
      idiomas_ocr: 'spa+eng',
      max_mb: 10,
    })
    vi.mocked(iaApi.analizarMinuta).mockResolvedValue(SUGERENCIA)
  })

  function renderPagina() {
    return renderWithProviders(
      <Routes>
        <Route path="/ddjj/:id/minuta" element={<MinutaPage />} />
        <Route path="/ddjj/:id" element={<p>Ficha de la declaración</p>} />
      </Routes>,
      { path: '/ddjj/d1/minuta', user: NOTARIO, raw: true },
    )
  }

  async function leer() {
    renderPagina()
    fireEvent.click(await screen.findByLabelText('Pegar el texto'))
    fireEvent.change(screen.getByLabelText('Texto de la minuta'), {
      target: { value: 'ESCRITURA NÚMERO CIENTO VEINTE (120)…' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Leer la minuta' }))
    await screen.findByText('Lo que leyó la Suite')
  }

  it('muestra respaldo, alertas y confianza baja antes de confirmar', async () => {
    await leer()
    expect(iaApi.analizarMinuta).toHaveBeenCalledWith('d1', {
      texto: 'ESCRITURA NÚMERO CIENTO VEINTE (120)…',
    })
    expect(
      screen.getByText('El monto en cifras no coincide con el escrito en letras.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/PESOS CUARENTA MILLONES/)).toBeInTheDocument()
    // La base imponible se precarga en formato local y se marca como dudosa.
    expect(screen.getByLabelText('Base imponible ($)')).toHaveValue('45.000.000,00')
    expect(screen.getByText(/confianza baja \(35 %\): verificalo/)).toBeInTheDocument()
  })

  it('no confirma sin la revisión explícita y envía lo que la persona dejó', async () => {
    vi.mocked(iaApi.ratificarActo).mockResolvedValue({
      sugerencia: { ...SUGERENCIA, estado: 'RATIFICADA' },
      acto: {} as ddjjApi.Acto,
    })
    await leer()
    const confirmar = screen.getByRole('button', { name: 'Confirmar y agregar el acto' })
    expect(confirmar).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Folio (opcional)'), { target: { value: '346' } })
    expect(screen.getByText('Corregido. La Suite había sugerido 345.')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText(/Revisé los datos contra la minuta/))
    expect(confirmar).toBeEnabled()
    fireEvent.click(confirmar)

    await waitFor(() => {
      expect(iaApi.ratificarActo).toHaveBeenCalledWith('s1', {
        escribano_id: 'e1',
        categoria: 'ESCRITURA_CON_VALOR',
        tipo_protocolo: 'GENERAL',
        numero_escritura: 120,
        folio: 346,
        fecha_acto: '2026-09-14',
        naturaleza: 'Compraventa',
        base_imponible: '45000000.00',
        acto_multiple: false,
      })
    })
    expect(await screen.findByText('Ficha de la declaración')).toBeInTheDocument()
  })

  it('cambiar un dato después de tildar la revisión exige volver a tildarla', async () => {
    await leer()
    fireEvent.click(screen.getByLabelText(/Revisé los datos contra la minuta/))
    fireEvent.change(screen.getByLabelText('N° de escritura'), { target: { value: '121' } })
    expect(screen.getByRole('button', { name: 'Confirmar y agregar el acto' })).toBeDisabled()
  })

  it('sin escribano identificado no preselecciona a nadie del equipo', async () => {
    vi.mocked(iaApi.analizarMinuta).mockResolvedValue({
      ...SUGERENCIA,
      campos: { ...SUGERENCIA.campos, escribano_id: campo(null, '0.0000') },
    })
    await leer()
    expect(screen.getByLabelText('Escribano')).toHaveValue('')
    expect(
      screen.getByText('La Suite no lo encontró en el documento: completalo.'),
    ).toBeInTheDocument()
  })
})

describe('alta de escribano con lectura del DNI', () => {
  const DNI: iaApi.Sugerencia = {
    ...SUGERENCIA,
    id: 'dni1',
    tipo: 'OCR_DNI',
    motor: 'dni-pdf417',
    ddjj_id: null,
    campos: {
      numero_documento: campo('12345678', '0.9800'),
      apellido: campo('Sintetico de la Prueba', '0.9800'),
      nombre: campo('Juan Carlos', '0.9800'),
      fecha_nacimiento: campo('1975-03-15', '0.9800'),
      cuit: campo('20123456786', '0.5000'),
    },
    alertas: [
      {
        codigo: 'COTEJAR_DOCUMENTO',
        nivel: 'AVISO',
        mensaje: 'Cotejá cada dato con el documento físico antes de confirmar el alta.',
        evidencia: null,
      },
    ],
  }

  it('precarga los datos, pide la revisión y ratifica en vez de crear directo', async () => {
    vi.resetAllMocks()
    vi.mocked(iaApi.analizarDni).mockResolvedValue(DNI)
    vi.mocked(iaApi.ratificarEscribano).mockResolvedValue({
      sugerencia: { ...DNI, estado: 'RATIFICADA' },
      escribano: { id: 'esc-1' } as padronApi.EscribanoDetalle,
    })
    renderWithProviders(<EscribanoNuevoPage />, {
      path: '/padron/escribanos/nuevo',
      user: { ...ESCRIBANO, permissions: ['escribanos:read', 'escribanos:write'] },
      routes: [{ path: '/padron/escribanos/:id', element: <p>Ficha del escribano</p> }],
    })
    const foto = new File(['x'], 'dni.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('Foto del DNI'), { target: { files: [foto] } })
    fireEvent.click(screen.getByRole('button', { name: 'Leer el DNI' }))

    expect(await screen.findByLabelText('Apellido')).toHaveValue('Sintetico de la Prueba')
    expect(screen.getByLabelText('CUIT')).toHaveValue('20-12345678-6')
    expect(screen.getByText(/confianza baja \(50 %\): verificalo/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Apellido'), {
      target: { value: 'Sintético de la Prueba' },
    })
    fireEvent.change(screen.getByLabelText('Número de matrícula'), { target: { value: '98765' } })
    fireEvent.change(screen.getByLabelText('Fecha de matriculación'), {
      target: { value: '2026-10-01' },
    })
    const alta = screen.getByRole('button', { name: 'Dar de alta' })
    expect(alta).toBeDisabled()
    const revision = screen.getByLabelText(/Revisé los datos personales contra el DNI/)
    fireEvent.click(revision)
    expect(alta).toBeEnabled()
    // Un cambio posterior exige volver a revisar.
    fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: 'María José' } })
    expect(alta).toBeDisabled()
    fireEvent.click(revision)
    expect(alta).toBeEnabled()
    fireEvent.click(alta)

    expect(await screen.findByText('Ficha del escribano')).toBeInTheDocument()
    expect(padronApi.createEscribano).not.toHaveBeenCalled()
    const [id, cuerpo] = vi.mocked(iaApi.ratificarEscribano).mock.calls[0] ?? []
    expect(id).toBe('dni1')
    expect(cuerpo?.persona.apellido).toBe('Sintético de la Prueba')
    expect(cuerpo?.persona.cuit).toBe('20-12345678-6')
    expect(cuerpo?.persona.nombre).toBe('María José')
  })
})
