import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as ddjjApi from '../ddjj/api'
import * as iaApi from './api'
import { IndicePage } from './IndicePage'

vi.mock('./api')
vi.mock('../ddjj/api')

const NOTARIO = { ...ESCRIBANO, permissions: ['ddjj:read_own', 'ddjj:create_own'] }

const ACTO: ddjjApi.Acto = {
  id: 'a1',
  escribano_id: 'e2',
  escribano: 'Sintético, Adscripto',
  matricula_numero: 102,
  cargo: 'ADSCRIPTO',
  tipo_protocolo: 'GENERAL',
  numero_escritura: 119,
  orden_en_escritura: 1,
  folio: 340,
  fecha_acto: '2026-09-10',
  naturaleza: 'Compraventa',
  categoria: 'ESCRITURA_CON_VALOR',
  base_imponible: '1000000.00',
  motivo_exencion: null,
  detalle_exencion: null,
  aporte: null,
  vigencia_id: null,
}

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
  cantidad_actos: 1,
  total_protocolos: null,
  vencimiento: '2026-10-28',
  created_at: '2026-10-01T12:00:00Z',
  actos: [ACTO],
  boletas: [],
  escribanos: [
    { id: 'e1', apellido_nombre: 'Sintético, Titular', matricula_numero: 101, cargo: 'TITULAR' },
    {
      id: 'e2',
      apellido_nombre: 'Sintético, Adscripto',
      matricula_numero: 102,
      cargo: 'ADSCRIPTO',
    },
  ],
  puede_operar: true,
  controles: {},
  huecos: [],
  proximos_numeros: { GENERAL: 120, AUXILIAR: 1 },
}

const campo = (valor: string | null, evidencia: string | null = null) => ({
  valor,
  confianza: '0.8500',
  regla: 'Del índice.',
  evidencia,
})

function renglon(
  id: string,
  numero: string,
  naturaleza: string,
  extra: Partial<iaApi.Sugerencia> = {},
): iaApi.Sugerencia {
  return {
    id,
    tipo: 'EXTRACCION_INDICE',
    estado: 'SUGERIDO_POR_IA',
    motor: 'indice-vision-deepseek',
    motor_version: '1.0',
    confianza: '0.8000',
    tiempo_ms: 5000,
    entrada: {
      origen: 'indice',
      mime_type: 'image/jpeg',
      caracteres: null,
      paginas: null,
      ocr: null,
    },
    campos: {
      tipo_protocolo: campo('GENERAL'),
      numero_escritura: campo(numero),
      folio: campo('345'),
      fecha_acto: campo('2026-09-14'),
      naturaleza: campo(naturaleza, `${naturaleza} · Pérez Juan a Gómez Ana`),
      categoria: campo('ESCRITURA_CON_VALOR'),
      base_imponible: campo('45000000.00'),
    },
    alertas: [],
    ddjj_id: 'd1',
    campos_modificados: null,
    acto_id: null,
    escribano_id: null,
    resuelto_en: null,
    created_at: '2026-10-27T12:00:00Z',
    ...extra,
  }
}

function render() {
  return renderWithProviders(
    <Routes>
      <Route path="/ddjj/:id/indice" element={<IndicePage />} />
    </Routes>,
    { path: '/ddjj/d1/indice', raw: true, user: NOTARIO },
  )
}

describe('foto del índice', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(ddjjApi.fetchDeclaracion).mockResolvedValue(DDJJ)
    vi.mocked(ddjjApi.verificarActo).mockResolvedValue({ aporte: '400000.00', controles: [] })
    vi.mocked(iaApi.fetchEstadoIa).mockResolvedValue({
      ocr_disponible: true,
      idiomas_ocr: 'spa',
      max_mb: 10,
    })
  })

  it('lee las fotos, deja revisar cada renglón y carga solo los incluidos', async () => {
    vi.mocked(iaApi.analizarIndice).mockResolvedValue({
      lote: 'l1',
      motor: 'indice-vision-deepseek',
      sugerencias: [
        renglon('s1', '120', 'Compraventa'),
        renglon('s2', '119', 'Hipoteca', {
          alertas: [
            {
              codigo: 'NUMERO_YA_DECLARADO',
              nivel: 'ADVERTENCIA',
              mensaje: 'La escritura N° 119 del protocolo general ya está declarada este año.',
              evidencia: null,
            },
          ],
        }),
      ],
    })
    vi.mocked(iaApi.ratificarActo).mockResolvedValue({
      sugerencia: renglon('s1', '120', 'Compraventa', { estado: 'RATIFICADA' }),
      acto: { ...ACTO, id: 'a2', numero_escritura: 120 },
    })
    vi.mocked(iaApi.descartarSugerencia).mockResolvedValue(
      renglon('s2', '119', 'Hipoteca', { estado: 'DESCARTADA' }),
    )
    render()

    const foto = new File(['x'], 'indice.jpg', { type: 'image/jpeg' })
    URL.createObjectURL = vi.fn(() => 'blob:foto')
    URL.revokeObjectURL = vi.fn()
    fireEvent.change(await screen.findByLabelText('Elegir fotos'), { target: { files: [foto] } })
    fireEvent.click(screen.getByRole('button', { name: 'Leer el índice' }))

    expect(await screen.findByText('2 renglones leídos')).toBeInTheDocument()
    expect(iaApi.analizarIndice).toHaveBeenCalledWith('d1', [foto])
    // El renglón con número ya declarado queda destildado y abierto para revisar.
    expect(screen.getByRole('checkbox', { name: 'Incluir la escritura 120' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Incluir la escritura 119' })).not.toBeChecked()
    expect(screen.getByText(/ya está declarada este año/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Cargar 1 acto' }))
    expect(await screen.findByText('Se cargó 1 acto.')).toBeInTheDocument()
    // El índice no dice quién autorizó: va el escribano del último acto cargado.
    expect(iaApi.ratificarActo).toHaveBeenCalledWith(
      's1',
      expect.objectContaining({
        escribano_id: 'e2',
        numero_escritura: 120,
        base_imponible: '45000000.00',
      }),
    )
    expect(iaApi.ratificarActo).toHaveBeenCalledTimes(1)
    await waitFor(() => {
      expect(iaApi.descartarSugerencia).toHaveBeenCalledWith(
        's2',
        'No incluido al revisar el índice.',
      )
    })
  })

  it('si un renglón falla al cargar, queda abierto con el motivo', async () => {
    vi.mocked(iaApi.analizarIndice).mockResolvedValue({
      lote: 'l1',
      motor: 'indice-vision-deepseek',
      sugerencias: [renglon('s1', '120', 'Compraventa')],
    })
    vi.mocked(iaApi.ratificarActo).mockRejectedValue(new Error('La fecha no es del período.'))
    render()

    URL.createObjectURL = vi.fn(() => 'blob:foto')
    URL.revokeObjectURL = vi.fn()
    fireEvent.change(await screen.findByLabelText('Elegir fotos'), {
      target: { files: [new File(['x'], 'indice.jpg', { type: 'image/jpeg' })] },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Leer el índice' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Cargar 1 acto' }))

    const fila = (await screen.findByRole('alert')).closest('li')
    expect(fila).not.toBeNull()
    expect(within(fila as HTMLElement).getByLabelText('N° de escritura')).toHaveValue('120')
    expect(iaApi.descartarSugerencia).not.toHaveBeenCalled()
  })
})
