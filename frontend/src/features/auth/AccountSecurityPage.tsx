import { useMutation, useQueryClient } from '@tanstack/react-query'
import { KeyRound, RefreshCw, ShieldCheck, ShieldOff } from 'lucide-react'
import { useState, type SyntheticEvent } from 'react'
import { useNavigate } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field, PasswordField } from '../../components/ui/Field'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { disableMfa, enableMfa, regenerateRecoveryCodes, startMfaSetup, type MfaSetup } from './api'
import { RecoveryCodes } from './RecoveryCodes'
import { roleLabel } from './roles'
import { SESSION_KEY, needsMfaEnrollment, useSession } from './session'

function groupSecret(secret: string): string {
  return secret.replace(/(.{4})/g, '$1 ').trim()
}

function CodeField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <Field
      label="Código de 6 dígitos"
      value={value}
      onChange={(e) => {
        onChange(e.target.value.replace(/\D/g, '').slice(0, 6))
      }}
      autoComplete="one-time-code"
      inputMode="numeric"
      pattern="[0-9]*"
      maxLength={6}
      placeholder="000000"
      className="max-w-48 [&_input]:tracking-[0.2em] [&_input]:tabular-nums"
      required
    />
  )
}

function Enrollment({ onCodes }: { onCodes: (codes: string[]) => void }) {
  const [setup, setSetup] = useState<MfaSetup | null>(null)
  const [code, setCode] = useState('')
  const start = useMutation({ mutationFn: startMfaSetup, onSuccess: setSetup })
  const enable = useMutation({ mutationFn: () => enableMfa(code), onSuccess: onCodes })

  if (!setup) {
    return (
      <div className="space-y-4 px-5 py-5 sm:px-6">
        {start.isError && <Alert tone="danger">{toProblem(start.error).detail}</Alert>}
        <p className="max-w-[65ch] text-sm text-ink-muted">
          Vas a necesitar una aplicación de autenticación en el teléfono, como Google Authenticator,
          Microsoft Authenticator o la del gestor de contraseñas que uses.
        </p>
        <Button
          variant="primary"
          icon={ShieldCheck}
          busy={start.isPending}
          busyLabel="Preparando…"
          onClick={() => {
            start.mutate()
          }}
        >
          Activar verificación en dos pasos
        </Button>
      </div>
    )
  }

  const onSubmit = (event: SyntheticEvent) => {
    event.preventDefault()
    enable.mutate()
  }
  return (
    <form onSubmit={onSubmit} className="grid gap-6 px-5 py-5 sm:grid-cols-[auto_1fr] sm:px-6">
      <div className="self-start justify-self-start rounded-control border border-line bg-white p-2">
        <img
          src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(setup.qr_svg)}`}
          alt="Código QR para la aplicación de autenticación"
          width={176}
          height={176}
          className="size-44"
        />
      </div>
      <div className="min-w-0 space-y-5">
        <ol className="list-decimal space-y-2 pl-5 text-sm text-ink">
          <li>Escaneá el código QR con la aplicación de autenticación.</li>
          <li>
            Si no podés escanearlo, cargá esta clave a mano:
            <span className="mt-1 block font-mono text-sm tracking-wider break-all text-brand-900 tabular-nums">
              {groupSecret(setup.secret)}
            </span>
          </li>
          <li>Ingresá el código de 6 dígitos que muestra la aplicación.</li>
        </ol>
        {enable.isError && <Alert tone="danger">{toProblem(enable.error).detail}</Alert>}
        <CodeField value={code} onChange={setCode} />
        <Button
          type="submit"
          variant="primary"
          icon={ShieldCheck}
          busy={enable.isPending}
          busyLabel="Verificando…"
          disabled={code.length !== 6}
        >
          Confirmar y activar
        </Button>
      </div>
    </form>
  )
}

function RegenerateDialog({
  open,
  onClose,
  onCodes,
}: {
  open: boolean
  onClose: () => void
  onCodes: (codes: string[]) => void
}) {
  const [code, setCode] = useState('')
  const regenerate = useMutation({
    mutationFn: () => regenerateRecoveryCodes(code),
    onSuccess: (codes) => {
      setCode('')
      onCodes(codes)
    },
  })
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Generar códigos nuevos"
      description="Los códigos anteriores dejan de servir en cuanto confirmes."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={RefreshCw}
            busy={regenerate.isPending}
            busyLabel="Generando…"
            disabled={code.length !== 6}
            onClick={() => {
              regenerate.mutate()
            }}
          >
            Generar códigos
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {regenerate.isError && <Alert tone="danger">{toProblem(regenerate.error).detail}</Alert>}
        <CodeField value={code} onChange={setCode} />
      </div>
    </Dialog>
  )
}

function DisableDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const disable = useMutation({
    mutationFn: () => disableMfa(password, code),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: SESSION_KEY })
      onClose()
    },
  })
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Desactivar verificación en dos pasos"
      description="Tu cuenta quedará protegida solo por la contraseña."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="danger"
            icon={ShieldOff}
            busy={disable.isPending}
            busyLabel="Desactivando…"
            disabled={!password || code.length !== 6}
            onClick={() => {
              disable.mutate()
            }}
          >
            Desactivar
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {disable.isError && <Alert tone="danger">{toProblem(disable.error).detail}</Alert>}
        <PasswordField
          label="Contraseña actual"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
          }}
          autoComplete="current-password"
        />
        <CodeField value={code} onChange={setCode} />
      </div>
    </Dialog>
  )
}

export function AccountSecurityPage() {
  const { user } = useSession()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [codes, setCodes] = useState<string[] | null>(null)
  const [dialog, setDialog] = useState<'regenerate' | 'disable' | null>(null)
  if (!user) return null

  const forced = needsMfaEnrollment(user)
  const finishCodes = async () => {
    setCodes(null)
    await queryClient.invalidateQueries({ queryKey: SESSION_KEY })
    if (forced) void navigate('/', { replace: true })
  }

  return (
    <>
      <PageHeader
        title="Seguridad de la cuenta"
        description="Tus datos de acceso y la verificación en dos pasos."
      />
      {forced && !codes && (
        <div className="mb-6">
          <Alert tone="warning" title="Activá la verificación en dos pasos para continuar">
            Tu rol tiene acceso a información sensible de la Caja. Hasta que la actives, el resto de
            la Suite queda bloqueado para esta cuenta.
          </Alert>
        </div>
      )}
      <div className="space-y-6">
        <Panel
          title="Verificación en dos pasos"
          description="Además de la contraseña, al ingresar te pedimos un código que genera tu teléfono."
          actions={
            user.mfa_enabled ? (
              <StatusIndicator tone="success" label="Activa" />
            ) : user.mfa_required ? (
              <StatusIndicator tone="warning" label="Obligatoria para tu rol" />
            ) : (
              <StatusIndicator tone="unknown" label="Inactiva" />
            )
          }
        >
          {codes ? (
            <div className="px-5 py-5 sm:px-6">
              <RecoveryCodes codes={codes} onDone={() => void finishCodes()} />
            </div>
          ) : user.mfa_enabled ? (
            <div className="flex flex-wrap gap-3 px-5 py-5 sm:px-6">
              <Button
                icon={RefreshCw}
                onClick={() => {
                  setDialog('regenerate')
                }}
              >
                Generar códigos de recuperación nuevos
              </Button>
              {!user.mfa_required && (
                <Button
                  variant="danger"
                  icon={ShieldOff}
                  onClick={() => {
                    setDialog('disable')
                  }}
                >
                  Desactivar
                </Button>
              )}
            </div>
          ) : (
            <Enrollment onCodes={setCodes} />
          )}
        </Panel>

        <Panel title="Datos de la cuenta">
          <dl className="divide-y divide-line">
            {[
              ['Nombre', user.full_name],
              ['Correo electrónico', user.email],
              ['CUIT', user.cuit],
              ['Roles', user.roles.map(roleLabel).join(', ') || 'Sin roles asignados'],
            ].map(([label, value]) => (
              <div
                key={label}
                className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 px-5 py-4 sm:px-6"
              >
                <dt className="text-sm font-medium text-ink-muted">{label}</dt>
                <dd className="text-ink tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="border-t border-line px-5 py-4 sm:px-6">
            <p className="flex items-center gap-2 text-sm text-ink-muted">
              <KeyRound aria-hidden="true" className="size-4" strokeWidth={2.25} />
              Para cambiar la contraseña usá “Olvidé mi contraseña” desde la pantalla de ingreso.
            </p>
          </div>
        </Panel>
      </div>

      <RegenerateDialog
        open={dialog === 'regenerate'}
        onClose={() => {
          setDialog(null)
        }}
        onCodes={(next) => {
          setDialog(null)
          setCodes(next)
        }}
      />
      <DisableDialog
        open={dialog === 'disable'}
        onClose={() => {
          setDialog(null)
        }}
      />
    </>
  )
}
