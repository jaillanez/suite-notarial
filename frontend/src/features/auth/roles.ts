export const ROLE_LABELS: Record<string, string> = {
  ROLE_ADMIN: 'Administración del sistema',
  ROLE_CAJA: 'Administración de Caja',
  ROLE_TESORERIA: 'Tesorería',
  ROLE_ESCRIBANO: 'Escribano',
  ROLE_AUDITOR: 'Auditoría',
  ROLE_PUBLICO: 'Público',
}

export function roleLabel(code: string): string {
  return ROLE_LABELS[code] ?? code
}
