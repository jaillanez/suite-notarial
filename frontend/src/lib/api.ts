import axios from 'axios'

/**
 * Cliente HTTP de la Suite. `withCredentials` habilita las cookies HttpOnly de sesión;
 * en desarrollo Vite proxea `/api` al backend, por lo que el origen es el mismo.
 */
export const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
  timeout: 10_000,
  headers: { 'X-Requested-With': 'XMLHttpRequest' },
})
