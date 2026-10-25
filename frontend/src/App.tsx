import { createBrowserRouter, Navigate, RouterProvider } from 'react-router'

import { AppShell, PublicShell } from './components/AppShell'
import { AuditPage } from './features/audit/AuditPage'
import { AccountSecurityPage } from './features/auth/AccountSecurityPage'
import { ForgotPasswordPage } from './features/auth/ForgotPasswordPage'
import { RedirectIfAuthenticated, RequireAuth, RequirePermission } from './features/auth/guards'
import { LoginPage } from './features/auth/LoginPage'
import { ResetPasswordPage } from './features/auth/ResetPasswordPage'
import { SystemStatusPage } from './features/health/SystemStatusPage'
import { HomePage } from './features/home/HomePage'
import { EscribanoNuevoPage } from './features/padron/EscribanoNuevoPage'
import { EscribanoPage } from './features/padron/EscribanoPage'
import { EscribanosPage } from './features/padron/EscribanosPage'
import { RegistroPage } from './features/padron/RegistroPage'
import { RegistrosPage } from './features/padron/RegistrosPage'
import { ConceptoPage } from './features/parametros/ConceptoPage'
import { ParametrosPage } from './features/parametros/ParametrosPage'
import { UsersPage } from './features/users/UsersPage'

const router = createBrowserRouter([
  {
    element: <RedirectIfAuthenticated />,
    children: [
      {
        element: <PublicShell />,
        children: [
          { path: '/ingresar', element: <LoginPage /> },
          { path: '/recuperar-clave', element: <ForgotPasswordPage /> },
        ],
      },
    ],
  },
  {
    // Accesible con o sin sesión: el enlace llega por correo.
    element: <PublicShell />,
    children: [{ path: '/restablecer-clave', element: <ResetPasswordPage /> }],
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: '/', element: <HomePage /> },
          { path: '/cuenta/seguridad', element: <AccountSecurityPage /> },
          { path: '/estado', element: <SystemStatusPage /> },
          {
            element: <RequirePermission permission="users:read" />,
            children: [{ path: '/usuarios', element: <UsersPage /> }],
          },
          {
            element: <RequirePermission permission="escribanos:read" />,
            children: [
              { path: '/padron/escribanos', element: <EscribanosPage /> },
              { path: '/padron/escribanos/:id', element: <EscribanoPage /> },
              { path: '/padron/registros', element: <RegistrosPage /> },
              { path: '/padron/registros/:id', element: <RegistroPage /> },
            ],
          },
          {
            element: <RequirePermission permission="escribanos:write" />,
            children: [{ path: '/padron/escribanos/nuevo', element: <EscribanoNuevoPage /> }],
          },
          {
            element: <RequirePermission permission="parameters:read" />,
            children: [
              { path: '/parametros', element: <ParametrosPage /> },
              { path: '/parametros/:id', element: <ConceptoPage /> },
            ],
          },
          {
            element: <RequirePermission permission="audit:read" />,
            children: [{ path: '/auditoria', element: <AuditPage /> }],
          },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])

export function App() {
  return <RouterProvider router={router} />
}
