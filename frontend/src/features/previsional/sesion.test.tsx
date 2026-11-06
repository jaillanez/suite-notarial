import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO } from '../../test/render'
import * as authApi from '../auth/api'
import { SessionProvider } from '../auth/SessionProvider'
import { SESSION_KEY, SessionContext, type SessionState } from '../auth/session'
import * as apiModule from './api'
import { PuntosPanel } from './PuntosPanel'

vi.mock('./api')
vi.mock('../auth/api')

const expirados: (() => void)[] = []
vi.mock('../../lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/api')>()
  return {
    ...original,
    onSessionExpired: (listener: () => void) => {
      expirados.push(listener)
      return () => undefined
    },
  }
})

const ANA = { ...ESCRIBANO, id: 'ana', permissions: ['puntos:read_own'] }
const LUIS = { ...ESCRIBANO, id: 'luis', permissions: ['puntos:read_own'] }

function informe(total: string): apiModule.InformePuntos {
  return {
    escribano: {
      id: 'e',
      apellido_nombre: 'X',
      matricula_numero: 1,
      tipo_documento: 'DNI',
      numero_documento: '1',
    },
    filas: [
      {
        anio: 2020,
        fecha_inicio: '2019-09-01',
        fecha_cierre: '2020-08-31',
        aportes: '1.00',
        puntos: total,
      },
    ],
    origenes: [],
    total_aportes: '1.00',
    total_puntos: total,
  }
}

function sesion(user: typeof ANA): SessionState {
  return { user, isLoading: false, can: (p) => user.permissions.includes(p) }
}

beforeEach(() => {
  expirados.length = 0
  vi.mocked(apiModule.fetchMisPuntos).mockReset()
})

describe('caché de «Mis puntos» por persona', () => {
  it('otra cuenta en el mismo navegador no ve los puntos cacheados de la anterior', async () => {
    vi.mocked(apiModule.fetchMisPuntos)
      .mockResolvedValueOnce(informe('11.000000'))
      .mockResolvedValueOnce(informe('22.000000'))
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    })
    const arbol = (user: typeof ANA) => (
      <QueryClientProvider client={client}>
        <SessionContext.Provider value={sesion(user)}>
          <MemoryRouter>
            <PuntosPanel />
          </MemoryRouter>
        </SessionContext.Provider>
      </QueryClientProvider>
    )
    const { rerender } = render(arbol(ANA))
    expect((await screen.findAllByText('11,000000')).length).toBeGreaterThan(0)

    rerender(arbol(LUIS))

    expect((await screen.findAllByText('22,000000')).length).toBeGreaterThan(0)
    expect(screen.queryByText('11,000000')).not.toBeInTheDocument()
    expect(apiModule.fetchMisPuntos).toHaveBeenCalledTimes(2)
  })
})

describe('limpieza de datos al cambiar la sesión', () => {
  function montar(client: QueryClient) {
    render(
      <QueryClientProvider client={client}>
        <SessionProvider>
          <span>app</span>
        </SessionProvider>
      </QueryClientProvider>,
    )
  }

  it('al ingresar otra persona se borran las consultas de la anterior', async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(ANA)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    montar(client)
    await waitFor(() => {
      expect(client.getQueryData(SESSION_KEY)).toEqual(ANA)
    })
    client.setQueryData(['previsional', 'puntos', 'ana', 'propios'], informe('11.000000'))

    client.setQueryData(SESSION_KEY, LUIS)

    await waitFor(() => {
      expect(client.getQueryData(['previsional', 'puntos', 'ana', 'propios'])).toBeUndefined()
    })
    expect(client.getQueryData(SESSION_KEY)).toEqual(LUIS)
  })

  it('al vencer la sesión no queda nada en caché', async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(ANA)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    montar(client)
    await waitFor(() => {
      expect(client.getQueryData(SESSION_KEY)).toEqual(ANA)
    })
    client.setQueryData(['previsional', 'puntos', 'ana', 'propios'], informe('11.000000'))

    expirados.forEach((avisar) => {
      avisar()
    })

    expect(client.getQueryData(['previsional', 'puntos', 'ana', 'propios'])).toBeUndefined()
    expect(client.getQueryData(SESSION_KEY)).toBeNull()
  })
})
