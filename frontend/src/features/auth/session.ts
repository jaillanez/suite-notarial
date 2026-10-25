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
