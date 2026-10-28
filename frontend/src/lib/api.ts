import axios, { AxiosError, type AxiosRequestConfig } from 'axios'

/**
 * Cliente HTTP de la Suite. La sesión viaja en cookies HttpOnly (`withCredentials`), y
 * `X-Requested-With` es la cabecera que el backend exige como defensa CSRF.
 * En desarrollo Vite proxea `/api`, por lo que el origen es el mismo.
 */
export const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
  timeout: 15_000,
  headers: { 'X-Requested-With': 'XMLHttpRequest' },
})

/** Ruta con un segmento `.` o `..` (también codificado). Los ids que llegan de la URL de la
 * página (parámetros de ruta o de búsqueda) se interpolan en las rutas de la API: uno armado a
 * propósito podría redirigir el pedido a otro endpoint con la sesión del usuario. */
export function rutaInsegura(url: string): boolean {
  const ruta = url.split('?')[0] ?? ''
  return ruta.split('/').some((segmento) => {
    let valor: string
    try {
      valor = decodeURIComponent(segmento)
    } catch {
      return true
    }
    return valor === '.' || valor === '..' || valor.includes('/') || valor.includes('\\')
  })
}

api.interceptors.request.use((config) => {
  if (rutaInsegura(config.url ?? '')) {
    throw new Error('Pedido rechazado: la dirección tiene un identificador inválido.')
  }
  return config
})

type RetriableConfig = AxiosRequestConfig & { _retried?: boolean }

const AUTH_PATHS_WITHOUT_REFRESH = ['/v1/auth/login', '/v1/auth/refresh', '/v1/auth/password-reset']

let refreshInFlight: Promise<void> | null = null
const sessionExpiredListeners = new Set<() => void>()

/** Avisa cuando la sesión no se pudo renovar (p. ej. para volver a la pantalla de ingreso). */
export function onSessionExpired(listener: () => void): () => void {
  sessionExpiredListeners.add(listener)
  return () => sessionExpiredListeners.delete(listener)
}

function refreshSession(): Promise<void> {
  // Un solo refresh a la vez: varias requests que vencen juntas esperan el mismo.
  refreshInFlight ??= api
    .post('/v1/auth/refresh')
    .then(() => undefined)
    .finally(() => {
      refreshInFlight = null
    })
  return refreshInFlight
}

api.interceptors.response.use(undefined, async (error: unknown) => {
  if (!(error instanceof AxiosError) || error.response?.status !== 401 || !error.config) {
    throw error
  }
  const config = error.config as RetriableConfig
  const url = config.url ?? ''
  if (config._retried || AUTH_PATHS_WITHOUT_REFRESH.some((p) => url.startsWith(p))) {
    throw error
  }
  config._retried = true
  try {
    await refreshSession()
  } catch {
    sessionExpiredListeners.forEach((listener) => {
      listener()
    })
    throw error
  }
  return api.request(config)
})

export interface Problem {
  status: number
  title: string
  detail: string
  type: string
  fieldErrors: Record<string, string>
}

const NETWORK_PROBLEM: Problem = {
  status: 0,
  title: 'Sin conexión',
  detail: 'No se pudo contactar al servidor. Revisá tu conexión y volvé a intentar.',
  type: 'about:blank',
  fieldErrors: {},
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** Convierte cualquier error de Axios en un Problem Details (RFC 7807) con mensajes en castellano. */
export function toProblem(error: unknown): Problem {
  if (!(error instanceof AxiosError)) {
    return { ...NETWORK_PROBLEM, detail: 'Ocurrió un error inesperado.' }
  }
  const response = error.response
  if (!response) return NETWORK_PROBLEM
  const body: unknown = response.data
  const fieldErrors: Record<string, string> = {}
  if (isRecord(body) && Array.isArray(body.errors)) {
    for (const item of body.errors) {
      if (isRecord(item) && Array.isArray(item.loc) && typeof item.msg === 'string') {
        const field = (item.loc as unknown[]).at(-1)
        if (typeof field === 'string') fieldErrors[field] = item.msg.replace(/^Value error, /, '')
      }
    }
  }
  return {
    status: response.status,
    title: isRecord(body) && typeof body.title === 'string' ? body.title : 'Error',
    detail:
      isRecord(body) && typeof body.detail === 'string'
        ? body.detail
        : 'El servidor no pudo completar la operación.',
    type: isRecord(body) && typeof body.type === 'string' ? body.type : 'about:blank',
    fieldErrors,
  }
}
