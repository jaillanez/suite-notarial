import { createContext, useContext } from 'react'

import type { SessionUser } from './api'

export const SESSION_KEY = ['session'] as const

export interface SessionState {
  user: SessionUser | null
  isLoading: boolean
  can: (permission: string) => boolean
}

export const SessionContext = createContext<SessionState | null>(null)

export function useSession(): SessionState {
  const context = useContext(SessionContext)
  if (!context) throw new Error('useSession debe usarse dentro de <SessionProvider>')
  return context
}

/** El rol exige 2FA y esta sesión todavía no lo verificó. */
export function needsMfaEnrollment(user: SessionUser): boolean {
  return user.mfa_required && !user.mfa_verified
}

const OMITIDO = 'suite:mfa-omitido:'

/** Se recomienda activar el 2FA y la persona todavía no eligió «Ingresar igual» en esta pestaña. */
export function mfaSugeridoPendiente(user: SessionUser): boolean {
  if (!user.mfa_sugerido) return false
  try {
    return sessionStorage.getItem(OMITIDO + user.id) === null
  } catch {
    return false
  }
}

/** «Ingresar igual»: no se vuelve a ofrecer hasta cerrar la pestaña. */
export function omitirMfaSugerido(user: SessionUser): void {
  try {
    sessionStorage.setItem(OMITIDO + user.id, '1')
  } catch {
    // Sin almacenamiento disponible, simplemente se vuelve a ofrecer la próxima vez.
  }
}
