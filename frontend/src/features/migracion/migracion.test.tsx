import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as api from './api'
import { CorridaPage } from './CorridaPage'
import { CorridasPage } from './CorridasPage'

vi.mock('./api')

const TESORERIA = {
  ...ESCRIBANO,
  full_name: 'Tesorería Demo',
  roles: ['ROLE_TESORERIA'],
  permissions: ['migracion:read', 'migracion:conformar'],
}

const ENTIDADES: api.CuadraturaEntidad[] = [
  {
    entidad: 'registros',
    control_filas: 6,
    leidas: 6,
    rechazadas: 0,
    cargadas: 6,
    cuadra_filas: true,
  },
  {
    entidad: 'boletas',
    control_filas: 72,
    leidas: 72,
    rechazadas: 1,
    cargadas: 71,
    cuadra_filas: true,
    control_importe: '1000123.79',
    importe_leido: '1000000.00',
    importe_rechazado: '500.00',
    importe_cargado: '999500.00',
    filas_importe_ilegible: 1,
    cuadra_importe: false,
  },
]

const INFORME: api.Informe = {
  cuadra: false,
  entidades: ENTIDADES,
  saldos: {
    registros: 6,
    deuda_total_origen: '1500.00',
    deuda_total_destino: '1500.00',
    diferencias: [],
  },
  boletas_por_estado: [{ estado: 'IMPAGA', filas: 3, importe: '1500.00' }],
  circunscripciones_nuevas: 2,
  bloqueantes: 1,
  advertencias: 0,
  observaciones_por_codigo: { VALOR_INVALIDO: 1 },
  codificaciones: { 'boletas.csv': 'utf-8' },
}

const CORRIDA: api.CorridaDetalle = {
  id: 'c1',
  modo: 'SIMULACRO',
  estado: 'SIMULADA',
  huella_lote: 'abcdef0123456789',
  homologacion: 'homologacion_ejemplo.json',
  homologacion_ejemplo: true,
  operador: 'Administración Demo',
  created_at: '2026-10-26T10:00:00Z',
  finalizada_en: '2026-10-26T10:00:01Z',
  duracion_ms: 1200,
  cuadra: false,
  bloqueantes: 1,
  advertencias: 0,
  conformidades: [],
  error: null,
  pendiente_para_definitiva: ['Hacen falta 3 simulacros que cuadren (hay 0).'],
  huella_homologacion: 'fedcba9876543210',
  homologacion_tablas: { cargo: { T: 'TITULAR', AC: 'SUPLENTE_INTERINO' } },
  informe: INFORME,
}

function renderCorrida() {
  return renderWithProviders(
    <Routes>
      <Route path="/migracion/:id" element={<CorridaPage />} />
    </Routes>,
    { path: '/migracion/c1', raw: true, user: TESORERIA },
  )
}

describe('migración', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.fetchObservaciones).mockResolvedValue({
      items: [
        {
          entidad: 'boletas',
          fila: 5,
          codigo_legado: 'BOL-1',
          codigo: 'VALOR_INVALIDO',
          severidad: 'BLOQUEANTE',
          mensaje: '«importe»: importe con más de dos decimales',
        },
      ],
      total: 1,
      page: 1,
      page_size: 25,
    })
  })

  it('lista las corridas con su cuadratura y conformidades', async () => {
    vi.mocked(api.fetchCorridas).mockResolvedValue([CORRIDA])
    renderWithProviders(<CorridasPage />, { user: TESORERIA })
    expect(await screen.findByText('Simulacro')).toBeInTheDocument()
    expect(screen.getByText('No cuadra')).toBeInTheDocument()
    expect(screen.getByText(/Tesorería pendiente, Caja pendiente/)).toBeInTheDocument()
  })

  it('explica por qué no cuadra, sin compensar: importe ilegible', async () => {
    vi.mocked(api.fetchCorrida).mockResolvedValue(CORRIDA)
    renderCorrida()
    expect(
      await screen.findByText('Boletas: 1 importe ilegible (no se redondean)'),
    ).toBeInTheDocument()
    expect(screen.getByText('Homologación de ejemplo')).toBeInTheDocument()
    expect(screen.getByText('Cargo en el registro')).toBeInTheDocument()
    expect(screen.getAllByText('$ 1.000.123,79').length).toBeGreaterThan(0)
    expect(await screen.findByText(/importe con más de dos decimales/)).toBeInTheDocument()
    // Un simulacro que no cuadró no se firma.
    expect(screen.queryByRole('button', { name: /Firmar conformidad/ })).not.toBeInTheDocument()
    expect(screen.getByText(/no se le puede dar conformidad/)).toBeInTheDocument()
  })

  it('Tesorería firma un simulacro que cuadró, tras tildar la revisión', async () => {
    const cuadrado: api.CorridaDetalle = {
      ...CORRIDA,
      cuadra: true,
      bloqueantes: 0,
      informe: { ...INFORME, cuadra: true },
    }
    vi.mocked(api.fetchCorrida).mockResolvedValue(cuadrado)
    vi.mocked(api.firmarConformidad).mockResolvedValue({
      ...cuadrado,
      conformidades: [
        {
          area: 'TESORERIA',
          firmante: 'Tesorería Demo',
          firmada_en: '2026-10-26T11:00:00Z',
          observaciones: null,
        },
      ],
    })
    renderCorrida()
    expect(await screen.findByText('Cuadra al centavo')).toBeInTheDocument()
    const firmar = screen.getByRole('button', { name: 'Firmar conformidad de Tesorería' })
    expect(firmar).toBeDisabled()
    fireEvent.click(screen.getByLabelText(/Revisé la cuadratura y las observaciones/))
    fireEvent.click(firmar)
    await waitFor(() => {
      expect(api.firmarConformidad).toHaveBeenCalledWith('c1', {
        area: 'TESORERIA',
        observaciones: null,
      })
    })
    expect(await screen.findByText('Firmó Tesorería Demo')).toBeInTheDocument()
  })
})
