import { screen } from '@testing-library/react'
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
  folio: null,
  fecha_acto: '2026-09-15',
  naturaleza: 'Compraventa',
  categoria: 'ESCRITURA_CON_VALOR',
  base_imponible: '100000000.00',
  aporte: null,
  vigencia_id: null,
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
  total_a_pagar: '1081699.06',
}

const BOLETA: apiModule.Boleta = {
  ...IMPORTES,
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
  fecha_pago: '2026-10-23',
  created_at: '2026-10-23T12:00:00Z',
  emitida_por: 'Caja Notarial',
  anulada_en: null,
  motivo_anulacion: null,
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
  })

  it('muestra la liquidación del borrador y avisa los valores a confirmar', async () => {
    vi.mocked(apiModule.fetchDeclaracion).mockResolvedValue(DDJJ)
    vi.mocked(apiModule.fetchLiquidacion).mockResolvedValue({
      ...IMPORTES,
      aportes: [{ acto_id: 'a1', aporte: '400000.00' }],
      vencimiento: '2026-10-28',
      fecha_pago: '2026-10-23',
      usa_valores_de_ejemplo: true,
    })

    renderFicha()

    expect(await screen.findByText('Incluye valores a confirmar')).toBeInTheDocument()
    expect(screen.getAllByText('$ 1.081.699,06').length).toBeGreaterThan(0)
    expect(screen.getAllByText('$ 400.000,00').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Agregar acto' })).toBeInTheDocument()
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
