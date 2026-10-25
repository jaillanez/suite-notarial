import { useMutation } from '@tanstack/react-query'
import { Mail } from 'lucide-react'
import { useState, type SyntheticEvent } from 'react'
import { Link, useLocation } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { toProblem } from '../../lib/api'
import { requestPasswordReset } from './api'

export function ForgotPasswordPage() {
  const location = useLocation()
  const initial = (location.state as { identifier?: string } | null)?.identifier ?? ''
  const [identifier, setIdentifier] = useState(initial)
  const request = useMutation({ mutationFn: () => requestPasswordReset(identifier.trim()) })

  const onSubmit = (event: SyntheticEvent) => {
    event.preventDefault()
    request.mutate()
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-brand-900">
        Restablecer contraseña
      </h1>
      {request.isSuccess ? (
        <div className="mt-8 space-y-6">
          <Alert tone="info" title="Revisá tu correo">
            {request.data} El enlace vence en 30 minutos. Si no lo ves, revisá la carpeta de correo
            no deseado.
          </Alert>
          <Link
            to="/ingresar"
            className="inline-flex min-h-11 items-center text-sm font-semibold underline underline-offset-4"
          >
            Volver a ingresar
          </Link>
        </div>
      ) : (
        <>
          <p className="mt-2 text-ink-muted">
            Indicá el correo o el CUIT de tu cuenta y te enviaremos un enlace para elegir una
            contraseña nueva.
          </p>
          <form onSubmit={onSubmit} className="mt-8 space-y-5" noValidate>
            {request.isError && <Alert tone="danger">{toProblem(request.error).detail}</Alert>}
            <Field
              label="Correo electrónico o CUIT"
              name="username"
              value={identifier}
              onChange={(e) => {
                setIdentifier(e.target.value)
              }}
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              autoFocus
            />
            <Button
              type="submit"
              variant="primary"
              icon={Mail}
              busy={request.isPending}
              busyLabel="Enviando…"
              disabled={identifier.trim().length < 3}
              className="w-full"
            >
              Enviar enlace
            </Button>
          </form>
          <p className="mt-6 text-sm">
            <Link
              to="/ingresar"
              className="inline-flex min-h-11 items-center font-semibold underline underline-offset-4"
            >
              Volver a ingresar
            </Link>
          </p>
        </>
      )}
    </div>
  )
}
