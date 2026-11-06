import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import { formatCelda } from '../reportes/formato'
import * as apiModule from './api'
import { formatPuntos } from './labels'
import { MisPuntosPage } from './MisPuntosPage'
import { PuntosPage } from './PuntosPage'
import { PuntosPanel } from './PuntosPanel'

vi.mock('./api')

const INFORME: apiModule.InformePuntos = {
  escribano: {
    id: 'e1',
    apellido_nombre: 'Prueba, Ana Sintética',
    matricula_numero: 101,
    tipo_documento: 'DNI',
    numero_documento: '30999888',
  },
  filas: [
    {
      anio: 1990,
      fecha_inicio: '1989-09-01',
      fecha_cierre: '1990-08-31',
      aportes: '82466.67',
      puntos: '97.639503',
    },
    {
      anio: 1991,
      fecha_inicio: '1990-09-01',
      fecha_cierre: '1991-08-31',
      aportes: '100.50',
      puntos: '50.000000',
    },
  ],
  origenes: [{ nombre_origen: 'PRUEBA Ana Sintética', vinculacion: 'EXACTA', ejercicios: 2 }],
  total_aportes: '82567.17',
  total_puntos: '147.639503',
}

const STAFF = {
  ...ESCRIBANO,
  roles: ['ROLE_CAJA'],
  permissions: ['puntos:read_all', 'puntos:manage', 'escribanos:read'],
}

beforeEach(() => {
  vi.mocked(apiModule.fetchMisPuntos).mockResolvedValue(INFORME)
  vi.mocked(apiModule.fetchPuntosEscribano).mockResolvedValue(INFORME)
  vi.mocked(apiModule.descargarInforme).mockResolvedValue()
  vi.mocked(apiModule.fetchEstadoCalculo).mockResolvedValue({
    habilitado: false,
    motivo: 'Falta la regla oficial de cálculo de la Caja (TODO(negocio)).',
  })
  vi.mocked(apiModule.fetchSinVincular).mockResolvedValue({
    items: [
      {
        nombre_origen: 'FICTICIO Pedro S.',
        estado: 'SIN_VINCULAR',
        ejercicios: 3,
        primer_anio: 1995,
        ultimo_anio: 1999,
        total_aportes: '1500.00',
        total_puntos: '310.250000',
        escribano: null,
      },
    ],
    total: 1,
    page: 1,
    page_size: 20,
  })
})

describe('formatos', () => {
  it('puntos con 6 decimales y columna DECIMAL del reporte', () => {
    expect(formatPuntos('1234.5')).toBe('1.234,500000')
    expect(
      formatCelda(
        {
          key: 'x',
          label: 'X',
          tipo: 'DECIMAL',
          total: false,
          visible: true,
          decimales: 4,
        },
        '2.5',
      ),
    ).toBe('2,5000')
  })
})

describe('mis puntos', () => {
  it('muestra la tabla por ejercicio, los totales y descarga el informe propio', async () => {
    renderWithProviders(<MisPuntosPage />, {
      user: { ...ESCRIBANO, permissions: ['puntos:read_own'] },
    })

    expect(await screen.findAllByText('97,639503')).not.toHaveLength(0)
    expect(screen.getAllByText('$ 82.567,17')).not.toHaveLength(0)
    expect(screen.getAllByText('147,639503')).not.toHaveLength(0)
    expect(screen.getAllByText('Total · 2 ejercicios')).not.toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Informe en PDF' }))
    await waitFor(() => {
      expect(apiModule.descargarInforme).toHaveBeenCalledWith(undefined)
    })
    expect(apiModule.fetchMisPuntos).toHaveBeenCalled()
  })

  it('sin datos explica qué hacer', async () => {
    vi.mocked(apiModule.fetchMisPuntos).mockResolvedValue({ ...INFORME, filas: [] })
    renderWithProviders(<MisPuntosPage />)
    expect(await screen.findByText(/No hay aportes ni puntos registrados/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Informe en PDF' })).not.toBeInTheDocument()
  })
})

describe('ficha del escribano', () => {
  it('el personal ve el origen del vínculo y descarga el informe de ese escribano', async () => {
    renderWithProviders(<PuntosPanel escribanoId="e1" />, { user: STAFF })

    expect(
      await screen.findByText(/«PRUEBA Ana Sintética» \(nombre idéntico\)/),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Informe en PDF' }))
    expect(apiModule.fetchPuntosEscribano).toHaveBeenCalledWith('e1')
    await waitFor(() => {
      expect(apiModule.descargarInforme).toHaveBeenCalledWith(INFORME.escribano)
    })
  })
})

describe('aportes y puntos (personal)', () => {
  it('lista los puntos sin vincular y deja el cálculo deshabilitado con su motivo', async () => {
    renderWithProviders(<PuntosPage />, { user: STAFF })

    const fila = (await screen.findByText('FICTICIO Pedro S.')).closest('li')
    expect(fila).not.toBeNull()
    expect(
      within(fila as HTMLElement).getByText(/Ejercicios 1995 a 1999 · 3 con datos/),
    ).toBeInTheDocument()
    expect(within(fila as HTMLElement).getByRole('button', { name: 'Vincular' })).toBeEnabled()
    expect(await screen.findByText(/Falta la regla oficial/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Calcular puntos' })).toBeDisabled()
  })

  it('sin puntos:manage no ofrece vincular', async () => {
    renderWithProviders(<PuntosPage />, {
      user: { ...STAFF, permissions: ['puntos:read_all'] },
    })
    expect(await screen.findByText('FICTICIO Pedro S.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Vincular' })).not.toBeInTheDocument()
  })
})
