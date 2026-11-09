import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/render'
import { ACargoPage } from './ACargoPage'
import * as apiModule from './api'
import { situacion } from './labels'

vi.mock('./api')

const BASE: apiModule.Designacion = {
  id: 'd1',
  registro_id: 'r1',
  numero_registro: 12,
  departamento: 'Capital',
  escribano_id: 'e2',
  apellido_nombre: 'Sintético, Designado',
  matricula_numero: 345,
  fecha_desde: '2026-10-05',
  fecha_hasta: '2026-10-31',
  motivo: 'Licencia del titular',
  estado: 'APROBADA',
  aporte: 'SOLO_ACTOS',
  rige_hoy: true,
  created_at: '2026-10-01T12:00:00Z',
  cargada_por: null,
  resuelta_por: null,
  resuelta_en: null,
  motivo_resolucion: null,
  puede_aprobar: false,
  puede_anular: true,
  puede_terminar: true,
  puede_fijar_aporte: false,
}

function pagina(items: apiModule.Designacion[]) {
  return { items, total: items.length, page: 1, page_size: 25 }
}

describe('situación de una designación', () => {
  it('distingue si rige hoy, si está programada o si ya se cumplió', () => {
    const hoy = '2026-10-23'
    expect(situacion(BASE, hoy).label).toBe('A cargo hoy')
    const futura = {
      ...BASE,
      rige_hoy: false,
      fecha_desde: '2026-11-01',
      fecha_hasta: '2026-11-30',
    }
    expect(situacion(futura, hoy).label).toBe('Programada')
    const pasada = {
      ...BASE,
      rige_hoy: false,
      fecha_desde: '2026-09-01',
      fecha_hasta: '2026-09-30',
    }
    expect(situacion(pasada, hoy).label).toBe('Cumplida')
    expect(situacion({ ...BASE, estado: 'PENDIENTE', rige_hoy: false }, hoy).label).toBe(
      'Espera aprobación',
    )
  })
})

describe('pantalla de escribano a cargo', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(apiModule.fetchRegistrosGestionables).mockResolvedValue([
      { id: 'r1', numero_registro: 12, departamento: 'Capital' },
    ])
  })

  it('el titular ve cómo rige la designación y sus acciones, sin aprobar', async () => {
    vi.mocked(apiModule.fetchAjustes).mockResolvedValue({
      a_cargo_requiere_aprobacion: false,
      updated_at: null,
      puede_editar: false,
    })
    vi.mocked(apiModule.fetchDesignaciones).mockResolvedValue(pagina([BASE]))
    renderWithProviders(<ACargoPage />)

    expect(await screen.findByText('Sintético, Designado')).toBeInTheDocument()
    expect(screen.getByText(/La designación rige desde que la cargás/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Terminar antes' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Anular' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Aprobar' })).not.toBeInTheDocument()
    // Ve qué aporta quien queda a cargo, pero lo fija la Caja.
    expect(screen.getByText('Solo sus actos')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cambiar aporte' })).not.toBeInTheDocument()
    // Solo la Caja elige el modo de aprobación.
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  })

  it('la Caja elige entre avisar y aprobar, y aprueba las pendientes', async () => {
    vi.mocked(apiModule.fetchAjustes).mockResolvedValue({
      a_cargo_requiere_aprobacion: false,
      updated_at: null,
      puede_editar: true,
    })
    vi.mocked(apiModule.fijarAjustes).mockResolvedValue({
      a_cargo_requiere_aprobacion: true,
      updated_at: null,
      puede_editar: true,
    })
    const pendiente = {
      ...BASE,
      estado: 'PENDIENTE' as const,
      rige_hoy: false,
      puede_aprobar: true,
      puede_terminar: false,
      cargada_por: 'titular@suite-notarial.example',
    }
    vi.mocked(apiModule.fetchDesignaciones).mockResolvedValue(pagina([pendiente]))
    vi.mocked(apiModule.aprobar).mockResolvedValue({ ...pendiente, estado: 'APROBADA' })
    renderWithProviders(<ACargoPage />)

    const aprueba = await screen.findByRole('radio', { name: /Aprueba la Caja/ })
    expect(screen.getByRole('radio', { name: /Alcanza con avisar/ })).toBeChecked()
    fireEvent.click(aprueba)
    await waitFor(() => {
      expect(apiModule.fijarAjustes).toHaveBeenCalledWith(true, expect.anything())
    })

    expect(screen.getByText('Espera aprobación')).toBeInTheDocument()
    expect(screen.getByText(/Cargada por titular@suite-notarial.example/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Aprobar' }))
    await waitFor(() => {
      expect(apiModule.aprobar).toHaveBeenCalledWith('d1')
    })
  })

  it('terminar antes pide fecha y motivo', async () => {
    vi.mocked(apiModule.fetchAjustes).mockResolvedValue({
      a_cargo_requiere_aprobacion: false,
      updated_at: null,
      puede_editar: false,
    })
    vi.mocked(apiModule.fetchDesignaciones).mockResolvedValue(pagina([BASE]))
    vi.mocked(apiModule.terminar).mockResolvedValue({ ...BASE, fecha_hasta: '2026-10-20' })
    renderWithProviders(<ACargoPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Terminar antes' }))
    const terminar = screen.getByRole('button', { name: 'Terminar' })
    expect(terminar).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Nueva fecha hasta'), {
      target: { value: '2026-10-20' },
    })
    fireEvent.change(screen.getByLabelText(/Motivo/), { target: { value: 'Volvió el titular' } })
    fireEvent.click(terminar)
    await waitFor(() => {
      expect(apiModule.terminar).toHaveBeenCalledWith('d1', '2026-10-20', 'Volvió el titular')
    })
  })

  it('la Caja fija qué aporta el escribano a cargo, con motivo', async () => {
    vi.mocked(apiModule.fetchAjustes).mockResolvedValue({
      a_cargo_requiere_aprobacion: false,
      updated_at: null,
      puede_editar: true,
    })
    const designacion = { ...BASE, puede_fijar_aporte: true }
    vi.mocked(apiModule.fetchDesignaciones).mockResolvedValue(pagina([designacion]))
    vi.mocked(apiModule.fijarAporte).mockResolvedValue({ ...designacion, aporte: 'CON_MINIMO' })
    renderWithProviders(<ACargoPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Cambiar aporte' }))
    const guardar = screen.getByRole('button', { name: 'Guardar' })
    expect(screen.getByRole('radio', { name: /Solo sus actos/ })).toBeChecked()
    fireEvent.click(screen.getByRole('radio', { name: /Con mínimo/ }))
    expect(guardar).toBeDisabled() // falta el motivo
    fireEvent.change(screen.getByLabelText(/Motivo/), { target: { value: 'Resolución 12/2026' } })
    fireEvent.click(guardar)
    await waitFor(() => {
      expect(apiModule.fijarAporte).toHaveBeenCalledWith('d1', 'CON_MINIMO', 'Resolución 12/2026')
    })
  })
})
