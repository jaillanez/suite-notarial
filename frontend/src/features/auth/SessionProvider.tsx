import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AxiosError } from 'axios'
import { useEffect, useRef, type ReactNode } from 'react'

import { onSessionExpired } from '../../lib/api'
import { fetchMe, type SessionUser } from './api'
import { SESSION_KEY, SessionContext, clearUserData, type SessionState } from './session'

async function fetchSession(): Promise<SessionUser | null> {
  try {
    return await fetchMe()
  } catch (error) {
    if (error instanceof AxiosError && error.response?.status === 401) return null
    throw error
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: SESSION_KEY,
    queryFn: fetchSession,
    staleTime: 60_000,
    retry: false,
  })

  useEffect(
    () =>
      onSessionExpired(() => {
        queryClient.setQueryData(SESSION_KEY, null)
        clearUserData(queryClient)
      }),
    [queryClient],
  )

  const user = query.data ?? null
  // Cambió la persona (venció la sesión, cerró, o ingresó otra cuenta): nada de la anterior queda
  // en caché. En la primera carga no hay anterior.
  const previo = useRef<string | null | undefined>(undefined)
  const actual = query.isPending ? undefined : (user?.id ?? null)
  useEffect(() => {
    if (actual === undefined) return
    if (previo.current !== undefined && previo.current !== actual) clearUserData(queryClient)
    previo.current = actual
  }, [actual, queryClient])
  const value: SessionState = {
    user,
    isLoading: query.isPending,
    // Solo decide qué se muestra. La autorización real la hace el backend en cada request.
    can: (permission) => user?.permissions.includes(permission) ?? false,
  }
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
