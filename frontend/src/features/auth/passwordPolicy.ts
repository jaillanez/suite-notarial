/** Espejo de la política del backend (app/modules/iam/passwords.py), solo para guiar al usuario. */
export interface PolicyCheck {
  label: string
  ok: boolean
}

export function checkPasswordPolicy(password: string): PolicyCheck[] {
  return [
    { label: 'Al menos 10 caracteres', ok: password.length >= 10 },
    { label: 'Una letra mayúscula', ok: /[A-ZÁÉÍÓÚÑ]/.test(password) },
    { label: 'Una letra minúscula', ok: /[a-záéíóúñ]/.test(password) },
    { label: 'Un número', ok: /[0-9]/.test(password) },
    { label: 'Un carácter especial', ok: /[^A-Za-z0-9ÁÉÍÓÚÑáéíóúñ]/.test(password) },
  ]
}
