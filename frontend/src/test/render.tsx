import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'

import type { SessionUser } from '../features/auth/api'
import { SessionContext } from '../features/auth/session'

export const ESCRIBANO: SessionUser = {
  id: '00000000-0000-4000-8000-000000000001',
  email: 'escribano@suite-notarial.example',
  full_name: 'Escribano Demo',
  cuit: '20-00000500-3',
  roles: ['ROLE_ESCRIBANO'],
  permissions: ['ddjj:read_own'],
  mfa_enabled: false,
  mfa_required: false,
  mfa_verified: false,
}

interface Options {
  user?: SessionUser | null
  path?: string
  routes?: { path: string; element: ReactElement }[]
  /** Monta `ui` tal cual (con sus propias <Routes>) en la URL `path`. */
  raw?: boolean
}

export function renderWithProviders(ui: ReactElement, options: Options = {}) {
  const { user = null, path = '/', routes = [], raw = false } = options
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const session = {
    user,
    isLoading: false,
    can: (permission: string) => user?.permissions.includes(permission) ?? false,
  }
  return render(
    <QueryClientProvider client={client}>
      <SessionContext.Provider value={session}>
        <MemoryRouter initialEntries={[path]}>
          {raw ? (
            ui
          ) : (
            <Routes>
              <Route path={path} element={ui} />
              {routes.map((r) => (
                <Route key={r.path} path={r.path} element={r.element} />
              ))}
            </Routes>
          )}
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
}
