import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import * as authApi from '../features/auth/api'
import { RedirectIfAuthenticated, RequireAuth } from '../features/auth/guards'
import { SessionProvider } from '../features/auth/SessionProvider'
import { ESCRIBANO } from '../test/render'
import { AppShell } from './AppShell'

vi.mock('../features/auth/api')

describe('cerrar sesión', () => {
  it('vuelve a la pantalla de ingreso sin recargar', async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(ESCRIBANO)
    vi.mocked(authApi.logout).mockResolvedValue()
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <SessionProvider>
          <MemoryRouter initialEntries={['/']}>
            <Routes>
              <Route element={<RedirectIfAuthenticated />}>
                <Route path="/ingresar" element={<p>Pantalla de ingreso</p>} />
              </Route>
              <Route element={<RequireAuth />}>
                <Route element={<AppShell />}>
                  <Route path="/" element={<p>Página de inicio</p>} />
                </Route>
              </Route>
            </Routes>
          </MemoryRouter>
        </SessionProvider>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Página de inicio')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: /Cerrar sesión/ })[0] as HTMLElement)

    await waitFor(() => {
      expect(screen.getByText('Pantalla de ingreso')).toBeInTheDocument()
    })
    expect(screen.queryByText('Página de inicio')).not.toBeInTheDocument()
    expect(authApi.logout).toHaveBeenCalledTimes(1)
    // No queda nada de la sesión en memoria salvo la sesión vacía.
    expect(client.getMutationCache().getAll()).toHaveLength(0)
    expect(
      client
        .getQueryCache()
        .getAll()
        .map((q) => q.queryKey),
    ).toEqual([['session']])
  })
})
