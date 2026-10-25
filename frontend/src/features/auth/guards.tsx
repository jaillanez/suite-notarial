import { Navigate, Outlet, useLocation } from 'react-router'

import { needsMfaEnrollment, useSession } from './session'

function FullPageLoading() {
  return (
    <div className="flex min-h-dvh items-center justify-center" aria-busy="true" aria-live="polite">
      <p className="text-sm text-ink-muted">Verificando la sesión…</p>
    </div>
  )
}

/** Exige sesión. Si el rol pide 2FA y falta, solo deja entrar a Seguridad de la cuenta. */
export function RequireAuth() {
  const { user, isLoading } = useSession()
  const location = useLocation()
  if (isLoading) return <FullPageLoading />
  if (!user) {
    return <Navigate to="/ingresar" replace state={{ from: location.pathname }} />
  }
  if (needsMfaEnrollment(user) && location.pathname !== '/cuenta/seguridad') {
    return <Navigate to="/cuenta/seguridad" replace />
  }
  return <Outlet />
}

/** Rutas para quien no inició sesión (ingreso, recuperación). */
export function RedirectIfAuthenticated() {
  const { user, isLoading } = useSession()
  if (isLoading) return <FullPageLoading />
  if (user) return <Navigate to="/" replace />
  return <Outlet />
}

/**
 * Oculta una sección a quien no tiene el permiso. Es solo experiencia de uso: el backend
 * vuelve a validar el permiso en cada request (SEC-01).
 */
export function RequirePermission({ permission }: { permission: string | string[] }) {
  const { can } = useSession()
  const options = Array.isArray(permission) ? permission : [permission]
  if (!options.some(can)) return <Navigate to="/" replace />
  return <Outlet />
}
