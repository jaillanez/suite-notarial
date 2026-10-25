import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, LogIn, ShieldCheck } from 'lucide-react'
import { useEffect, useRef, useState, type SyntheticEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field, PasswordField } from '../../components/ui/Field'
import { toProblem } from '../../lib/api'
import { login, loginMfa, type LoginResult } from './api'
import { SESSION_KEY } from './session'

type Step = 'password' | 'mfa'

export function LoginPage() {
  const [step, setStep] = useState<Step>('password')
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const codeRef = useRef<HTMLInputElement>(null)
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  const finish = (result: LoginResult) => {
    if (result.status === 'mfa_required') {
      setStep('mfa')
      return
    }
    queryClient.setQueryData(SESSION_KEY, result.user)
    void navigate(from, { replace: true })
  }

  const passwordStep = useMutation({
    mutationFn: () => login(identifier, password),
    onSuccess: finish,
  })
  const mfaStep = useMutation({
    mutationFn: () => loginMfa(code),
    onSuccess: finish,
  })

  useEffect(() => {
    if (step === 'mfa') codeRef.current?.focus()
  }, [step, useRecovery])

  const onPassword = (event: SyntheticEvent) => {
    event.preventDefault()
    passwordStep.mutate()
  }
  const onMfa = (event: SyntheticEvent) => {
    event.preventDefault()
    mfaStep.mutate()
  }
  const backToPassword = () => {
    setStep('password')
    setCode('')
    setPassword('')
    mfaStep.reset()
  }

  if (step === 'mfa') {
    const problem = mfaStep.isError ? toProblem(mfaStep.error) : null
    const expired = problem?.detail.startsWith('La verificación venció')
    return (
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-brand-900">
          Verificación en dos pasos
        </h1>
        <p className="mt-2 text-ink-muted">
          {useRecovery
            ? 'Ingresá uno de los códigos de recuperación que guardaste al activar la verificación. Cada código sirve una sola vez.'
            : 'Abrí tu aplicación de autenticación e ingresá el código de 6 dígitos de la Suite Notarial.'}
        </p>
        <form onSubmit={onMfa} className="mt-8 space-y-5" noValidate>
          {problem && (
            <Alert
              tone="danger"
              action={
                expired ? (
                  <Button variant="secondary" onClick={backToPassword} icon={ArrowLeft}>
                    Volver a ingresar
                  </Button>
                ) : undefined
              }
            >
              {problem.detail}
            </Alert>
          )}
          <Field
            ref={codeRef}
            label={useRecovery ? 'Código de recuperación' : 'Código de verificación'}
            name="code"
            value={code}
            onChange={(e) => {
              setCode(e.target.value)
            }}
            autoComplete="one-time-code"
            inputMode={useRecovery ? 'text' : 'numeric'}
            pattern={useRecovery ? undefined : '[0-9]*'}
            maxLength={useRecovery ? 14 : 6}
            placeholder={useRecovery ? 'XXXX-XXXX-XXXX' : '000000'}
            className="[&_input]:tracking-[0.2em] [&_input]:tabular-nums"
            required
          />
          <Button
            type="submit"
            variant="primary"
            icon={ShieldCheck}
            busy={mfaStep.isPending}
            busyLabel="Verificando…"
            disabled={code.trim().length < 6}
            className="w-full"
          >
            Verificar e ingresar
          </Button>
        </form>
        <div className="mt-6 flex flex-col items-start gap-1">
          <button
            type="button"
            onClick={() => {
              setUseRecovery((v) => !v)
              setCode('')
              mfaStep.reset()
            }}
            className="min-h-11 cursor-pointer text-sm font-semibold text-action-700 underline underline-offset-4 hover:text-brand-800"
          >
            {useRecovery ? 'Usar el código de la aplicación' : 'No tengo acceso a la aplicación'}
          </button>
          <button
            type="button"
            onClick={backToPassword}
            className="min-h-11 cursor-pointer text-sm font-semibold text-action-700 underline underline-offset-4 hover:text-brand-800"
          >
            Ingresar con otra cuenta
          </button>
        </div>
      </div>
    )
  }

  const problem = passwordStep.isError ? toProblem(passwordStep.error) : null
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-brand-900">Ingresar</h1>
      <p className="mt-2 text-ink-muted">
        Accedé a la Suite Notarial con tu correo electrónico o tu CUIT.
      </p>
      <form onSubmit={onPassword} className="mt-8 space-y-5" noValidate>
        {problem && <Alert tone="danger">{problem.detail}</Alert>}
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
        <PasswordField
          label="Contraseña"
          name="password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
          }}
          autoComplete="current-password"
          required
        />
        <Button
          type="submit"
          variant="primary"
          icon={LogIn}
          busy={passwordStep.isPending}
          busyLabel="Ingresando…"
          disabled={!identifier.trim() || !password}
          className="w-full"
        >
          Ingresar
        </Button>
      </form>
      <p className="mt-6 text-sm">
        <Link
          to="/recuperar-clave"
          state={{ identifier }}
          className="inline-flex min-h-11 items-center font-semibold underline underline-offset-4"
        >
          Olvidé mi contraseña
        </Link>
      </p>
    </div>
  )
}
