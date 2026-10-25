import { api } from '../../lib/api'
import type { Page } from '../users/api'

export interface AuditEntry {
  id: string
  event_timestamp: string
  event_type: string
  severity: 'INFO' | 'WARNING' | 'CRITICAL'
  actor_user_id: string | null
  actor_email: string | null
  target_user_id: string | null
  target_email: string | null
  ip_address: string | null
  correlation_id: string | null
  old_value: Record<string, unknown> | null
  new_value: Record<string, unknown> | null
  details: Record<string, unknown> | null
}

export async function fetchAuditLogs(params: {
  page: number
  pageSize: number
  eventType: string
}): Promise<Page<AuditEntry>> {
  const query: Record<string, string | number> = { page: params.page, page_size: params.pageSize }
  if (params.eventType) query.event_type = params.eventType
  return (await api.get<Page<AuditEntry>>('/v1/audit/security-logs', { params: query })).data
}

export const EVENT_LABELS: Record<string, string> = {
  LOGIN_SUCCESS: 'Ingreso',
  LOGIN_FAILED: 'Ingreso fallido',
  LOGIN_LOCKED: 'Cuenta bloqueada por intentos',
  LOGIN_MFA_CHALLENGE: 'Pedido de segundo factor',
  LOGIN_MFA_FAILED: 'Segundo factor incorrecto',
  LOGIN_RECOVERY_CODE_USED: 'Ingreso con código de recuperación',
  LOGOUT: 'Cierre de sesión',
  SESSION_REFRESHED: 'Sesión renovada',
  SESSION_REUSE_DETECTED: 'Reuso de sesión detectado',
  MFA_ENROLLMENT_STARTED: 'Inicio de alta de 2FA',
  MFA_ENABLED: '2FA activado',
  MFA_DISABLED: '2FA desactivado',
  MFA_RECOVERY_CODES_REGENERATED: 'Códigos de recuperación nuevos',
  PASSWORD_RESET_REQUESTED: 'Pedido de restablecer contraseña',
  PASSWORD_RESET_COMPLETED: 'Contraseña restablecida',
  PASSWORD_RESET_REJECTED: 'Enlace de restablecimiento rechazado',
  PASSWORD_CHANGED: 'Contraseña cambiada',
  USER_CREATED: 'Alta de usuario',
  USER_STATUS_CHANGED: 'Cambio de estado de usuario',
  USER_ROLES_CHANGED: 'Cambio de roles',
  PERMISSION_DENIED: 'Acceso denegado',
}
