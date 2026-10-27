import { useMutation } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import { useState, type SyntheticEvent } from 'react'
import { Link } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { PasswordField } from '../../components/ui/Field'
import { toProblem } from '../../lib/api'
import { confirmPasswordReset } from './api'
import { checkPasswordPolicy } from './passwordPolicy'
import { RequisitosClave } from './RequisitosClave'

/**
 * Lee el token del fragmento (`#token=...`), que el navegador nunca envía al servidor, y lo
 * borra de la barra de direcciones para que no quede en el historial ni en capturas.
 */
function takeTokenFromHash(): string | null {
  const params = new URLSearchParams(window.location.hash.slice(1))
  const token = params.get('token')
  if (token) {
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
  }
  return token
}

export function ResetPasswordPage() {
  const [token] = useState(takeTokenFromHash)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const confirmMutation = useMutation({
    mutationFn: () => confirmPasswordReset(token ?? '', password),
  })

  const checks = checkPasswordPolicy(password)
  const policyOk = checks.every((c) => c.ok)
  const mismatch = confirm.length > 0 && confirm !== password

  const onSubmit = (event: SyntheticEvent) => {
    event.preventDefault()
    if (policyOk && !mismatch) confirmMutation.mutate()
  }

  if (!token) {
    return (
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-brand-900">Enlace incompleto</h1>
        <div className="mt-8 space-y-6">
          <Alert tone="warning">
            Este enlace no tiene el código de recuperación. Abrilo tal cual llegó en el correo o
            pedí uno nuevo.
          </Alert>
          <Link
            to="/recuperar-clave"
            className="inline-flex min-h-11 items-center text-sm font-semibold underline underline-offset-4"
          >
            Pedir un enlace nuevo
          </Link>
        </div>
      </div>
    )
  }

  if (confirmMutation.isSuccess) {
    return (
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-brand-900">
          Contraseña actualizada
        </h1>
        <div className="mt-8 space-y-6">
          <Alert tone="success">
            {confirmMutation.data} Por seguridad cerramos todas las sesiones abiertas.
          </Alert>
          <Link
            to="/ingresar"
            replace
            className="inline-flex min-h-11 items-center rounded-control bg-brand-800 px-4 text-sm font-semibold text-white no-underline hover:bg-brand-700"
          >
            Ir a ingresar
          </Link>
        </div>
      </div>
    )
  }

  const problem = confirmMutation.isError ? toProblem(confirmMutation.error) : null
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-brand-900">Elegí una contraseña</h1>
      <p className="mt-2 text-ink-muted">
        La nueva contraseña reemplaza a la anterior en cuanto la guardes.
      </p>
      <form onSubmit={onSubmit} className="mt-8 space-y-5" noValidate>
        {problem && (
          <Alert
            tone="danger"
            action={
              problem.status === 400 ? (
                <Link
                  to="/recuperar-clave"
                  className="text-sm font-semibold underline underline-offset-4"
                >
                  Pedir un enlace nuevo
                </Link>
              ) : undefined
            }
          >
            {problem.detail}
          </Alert>
        )}
        <PasswordField
          label="Contraseña nueva"
          name="new-password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
          }}
          autoComplete="new-password"
          required
          autoFocus
          hint={<RequisitosClave checks={checks} />}
        />
        <PasswordField
          label="Repetí la contraseña"
          name="confirm-password"
          value={confirm}
          onChange={(e) => {
            setConfirm(e.target.value)
          }}
          autoComplete="new-password"
          required
          error={mismatch ? 'Las contraseñas no coinciden.' : undefined}
        />
        <Button
          type="submit"
          variant="primary"
          icon={KeyRound}
          busy={confirmMutation.isPending}
          busyLabel="Guardando…"
          disabled={!policyOk || mismatch || confirm.length === 0}
          className="w-full"
        >
          Guardar contraseña
        </Button>
      </form>
    </div>
  )
}
