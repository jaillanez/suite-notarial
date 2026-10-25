import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../../lib/api'
import { SystemStatusPage } from './SystemStatusPage'

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SystemStatusPage />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('SystemStatusPage', () => {
  it('muestra servicios operativos con la hora en San Juan', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: { status: 'ok', db: 'up', time_utc: '2026-10-25T13:04:05Z' },
    })
    renderPage()

    expect(await screen.findByText('Todos los servicios operativos')).toBeInTheDocument()
    expect(screen.getAllByText('Operativa')).toHaveLength(2)
    expect(screen.getByText('25/10/2026 10:04:05')).toBeInTheDocument()
  })

  it('muestra estado degradado cuando la base no responde', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      data: { status: 'degraded', db: 'down', time_utc: '2026-10-25T13:04:05Z' },
    })
    renderPage()

    expect(await screen.findByText('Servicio degradado')).toBeInTheDocument()
    expect(screen.getByText('Sin conexión')).toBeInTheDocument()
  })

  it('informa cuando la API no responde', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('Network Error'))
    renderPage()

    expect(await screen.findByText('No se pudo contactar la API')).toBeInTheDocument()
    expect(screen.getByText('Sin respuesta')).toBeInTheDocument()
  })
})
