import { api } from '../../lib/api'

export interface SessionUser {
  id: string
  email: string
  full_name: string
  cuit: string
  roles: string[]
  permissions: string[]
  mfa_enabled: boolean
  mfa_required: boolean
  mfa_verified: boolean
  /** El rol lo exigiría, pero en este entorno es una recomendación (no bloquea). */
  mfa_sugerido?: boolean
}

export interface LoginResult {
  status: 'authenticated' | 'mfa_required'
  user: SessionUser | null
  /** Con mfa_required: el código llega por correo o lo genera la aplicación. */
  mfa_method?: 'totp' | 'email' | null
  /** Dirección a la que se mandó el código, enmascarada («h***@gmail.com»). */
  email_hint?: string | null
}

export interface MfaSetup {
  secret: string
  otpauth_uri: string
  qr_svg: string
}

export async function fetchMe(): Promise<SessionUser> {
  return (await api.get<SessionUser>('/v1/auth/me')).data
}

export async function login(identifier: string, password: string): Promise<LoginResult> {
  return (await api.post<LoginResult>('/v1/auth/login', { identifier, password })).data
}

/** `recordarEquipo`: no volver a pedir el segundo paso en este navegador (30 días). */
export async function loginMfa(code: string, recordarEquipo = false): Promise<LoginResult> {
  return (
    await api.post<LoginResult>('/v1/auth/login/mfa', { code, recordar_equipo: recordarEquipo })
  ).data
}

/** Manda un código nuevo por correo para el ingreso en curso (anula el anterior). */
export async function reenviarCodigo(): Promise<LoginResult> {
  return (await api.post<LoginResult>('/v1/auth/login/codigo')).data
}

export async function logout(): Promise<void> {
  await api.post('/v1/auth/logout')
}

export async function requestPasswordReset(identifier: string): Promise<string> {
  return (await api.post<{ message: string }>('/v1/auth/password-reset/request', { identifier }))
    .data.message
}

export async function confirmPasswordReset(token: string, newPassword: string): Promise<string> {
  return (
    await api.post<{ message: string }>('/v1/auth/password-reset/confirm', {
      token,
      new_password: newPassword,
    })
  ).data.message
}

export async function startMfaSetup(): Promise<MfaSetup> {
  return (await api.post<MfaSetup>('/v1/auth/mfa/setup')).data
}

export async function enableMfa(code: string): Promise<string[]> {
  return (await api.post<{ recovery_codes: string[] }>('/v1/auth/mfa/enable', { code })).data
    .recovery_codes
}

export async function disableMfa(password: string, code: string): Promise<void> {
  await api.post('/v1/auth/mfa/disable', { password, code })
}

export async function regenerateRecoveryCodes(code: string): Promise<string[]> {
  return (await api.post<{ recovery_codes: string[] }>('/v1/auth/mfa/recovery-codes', { code }))
    .data.recovery_codes
}

export interface Perfil {
  email: string
  full_name: string
  cuit: string
  phone_number: string | null
  /** El nombre de un escribano lo lleva el padrón: lo cambia la Caja. */
  nombre_editable: boolean
}

export async function fetchPerfil(): Promise<Perfil> {
  return (await api.get<Perfil>('/v1/auth/perfil')).data
}

export async function actualizarPerfil(datos: {
  full_name?: string
  phone_number: string
}): Promise<Perfil> {
  return (await api.patch<Perfil>('/v1/auth/perfil', datos)).data
}

export async function cambiarContrasena(actual: string, nueva: string): Promise<string> {
  return (
    await api.post<{ message: string }>('/v1/auth/password/change', {
      current_password: actual,
      new_password: nueva,
    })
  ).data.message
}

/** Pide cambiar el correo de ingreso: llega un enlace a la dirección nueva para confirmarla. */
export async function pedirCambioCorreo(nuevoEmail: string, password: string): Promise<string> {
  return (
    await api.post<{ message: string }>('/v1/auth/perfil/correo', {
      nuevo_email: nuevoEmail,
      password,
    })
  ).data.message
}

export async function confirmarCambioCorreo(token: string): Promise<string> {
  return (await api.post<{ message: string }>('/v1/auth/perfil/correo/confirmar', { token })).data
    .message
}
