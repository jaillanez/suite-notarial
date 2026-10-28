import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import { AccountSecurityPage } from './AccountSecurityPage'
import { RequireAuth, RequirePermission } from './guards'

function protectedTree(child: string) {
  return (
    <Routes>
      <Route element={<RequireAuth />}>
        <Route path="/usuarios" element={<p>{child}</p>} />
      </Route>
      <Route path="/ingresar" element={<p>Pantalla de ingreso</p>} />
      <Route path="/cuenta/seguridad" element={<p>Seguridad</p>} />
    </Routes>
  )
}

describe('guards', () => {
  it('sin sesión lleva al ingreso', () => {
    renderWithProviders(protectedTree('Usuarios'), { path: '/usuarios', user: null, raw: true })
    expect(screen.getByText('Pantalla de ingreso')).toBeInTheDocument()
  })

  it('un rol que exige 2FA sin verificar solo puede ir a Seguridad', () => {
    const admin = { ...ESCRIBANO, roles: ['ROLE_ADMIN'], mfa_required: true }
    renderWithProviders(protectedTree('Usuarios'), { path: '/usuarios', user: admin, raw: true })
    expect(screen.getByText('Seguridad')).toBeInTheDocument()
  })

  it('donde el 2FA es solo recomendado, se ofrece y se puede «Ingresar igual»', () => {
    sessionStorage.clear()
    const caja = { ...ESCRIBANO, id: 'u-caja', roles: ['ROLE_CAJA'], mfa_sugerido: true }
    renderWithProviders(
      <Routes>
        <Route element={<RequireAuth />}>
          <Route path="/" element={<p>Inicio de la Suite</p>} />
          <Route path="/cuenta/seguridad" element={<AccountSecurityPage />} />
        </Route>
      </Routes>,
      { path: '/', user: caja, raw: true },
    )
    expect(
      screen.getByText('Te recomendamos activar la verificación en dos pasos'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ingresar igual' }))
    expect(screen.getByText('Inicio de la Suite')).toBeInTheDocument()
  })

  it('sin el permiso no muestra la sección', () => {
    renderWithProviders(
      <Routes>
        <Route element={<RequirePermission permission="users:read" />}>
          <Route path="/usuarios" element={<p>Usuarios</p>} />
        </Route>
        <Route path="/" element={<p>Inicio</p>} />
      </Routes>,
      { path: '/usuarios', user: ESCRIBANO, raw: true },
    )
    expect(screen.queryByText('Usuarios')).not.toBeInTheDocument()
    expect(screen.getByText('Inicio')).toBeInTheDocument()
  })
})
