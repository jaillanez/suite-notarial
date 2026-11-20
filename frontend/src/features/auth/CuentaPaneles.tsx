import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Mail, Save } from 'lucide-react'
import { useState, type SyntheticEvent } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field, PasswordField } from '../../components/ui/Field'
import { Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import {
  actualizarPerfil,
  cambiarContrasena,
  fetchPerfil,
  pedirCambioCorreo,
  type Perfil,
} from './api'
import { checkPasswordPolicy } from './passwordPolicy'
import { RequisitosClave } from './RequisitosClave'
import { roleLabel } from './roles'
import { SESSION_KEY, useSession } from './session'

const PERFIL_KEY = ['cuenta', 'perfil'] as const

function Dato({ label, children }: { label: string; children: string }) {
  return (
    <div>
      <dt className="text-sm font-medium text-ink-muted">{label}</dt>
      <dd className="mt-1 text-ink tabular-nums [overflow-wrap:anywhere]">{children}</dd>
    </div>
  )
}

/** Lo que se puede tipear en un teléfono: números y los separadores habituales. */
const NO_TELEFONO = /[^\d\s()+.-]/g
const MIN_DIGITOS = 8
const MAX_DIGITOS = 15

/** Mismo criterio que el servidor: entre 8 y 15 números, con la característica. */
function errorTelefono(valor: string): string | null {
  const v = valor.trim()
  if (!v) return null
  const digitos = v.replace(/\D/g, '').length
  if (digitos < MIN_DIGITOS || digitos > MAX_DIGITOS)
    return `Tiene que tener entre ${String(MIN_DIGITOS)} y ${String(MAX_DIGITOS)} números, con la característica.`
  return null
}

function CambioCorreoDialog({ actual, onClose }: { actual: string; onClose: () => void }) {
  const [correo, setCorreo] = useState('')
  const [clave, setClave] = useState('')
  const pedir = useMutation({ mutationFn: () => pedirCambioCorreo(correo.trim(), clave) })
  const problem = pedir.isError ? toProblem(pedir.error) : null
  const valido = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(correo.trim()) && clave.length > 0
  return (
    <Dialog
      open
      onClose={onClose}
      title="Cambiar el correo de ingreso"
      description={`Hoy ingresás con ${actual}. Te mandamos un enlace a la dirección nueva: el cambio se hace cuando lo abrís.`}
      footer={
        pedir.isSuccess ? (
          <Button variant="primary" onClick={onClose}>
            Entendido
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>Cancelar</Button>
            <Button
              variant="primary"
              icon={Mail}
              busy={pedir.isPending}
              busyLabel="Enviando…"
              disabled={!valido}
              onClick={() => {
                pedir.mutate()
              }}
            >
              Enviar el enlace
            </Button>
          </>
        )
      }
    >
      {pedir.isSuccess ? (
        <Alert tone="success">{pedir.data}</Alert>
      ) : (
        <div className="grid gap-4">
          {problem && <Alert tone="danger">{problem.detail}</Alert>}
          <Field
            label="Correo nuevo"
            type="email"
            autoComplete="email"
            value={correo}
            error={problem?.fieldErrors.nuevo_email}
            onChange={(e) => {
              setCorreo(e.target.value)
            }}
          />
          <PasswordField
            label="Tu contraseña"
            autoComplete="current-password"
            value={clave}
            hint="Para confirmar que sos vos."
            onChange={(e) => {
              setClave(e.target.value)
            }}
          />
        </div>
      )}
    </Dialog>
  )
}

function FormPerfil({ perfil }: { perfil: Perfil }) {
  const { user } = useSession()
  const queryClient = useQueryClient()
  const [telefono, setTelefono] = useState(perfil.phone_number ?? '')
  const [guardado, setGuardado] = useState(false)
  const [cambiandoCorreo, setCambiandoCorreo] = useState(false)
  const guardar = useMutation({
    mutationFn: () => actualizarPerfil({ phone_number: telefono.trim() }),
    onSuccess: async (nuevo) => {
      queryClient.setQueryData(PERFIL_KEY, nuevo)
      await queryClient.invalidateQueries({ queryKey: SESSION_KEY })
      setGuardado(true)
    },
  })
  const cambios = telefono.trim() !== (perfil.phone_number ?? '')
  const problem = guardar.isError ? toProblem(guardar.error) : null
  const invalido = errorTelefono(telefono)
  const enviar = (e: SyntheticEvent) => {
    e.preventDefault()
    setGuardado(false)
    if (!invalido) guardar.mutate()
  }

  return (
    <form onSubmit={enviar} className="grid gap-5 px-5 py-5 sm:px-6" noValidate>
      {problem && <Alert tone="danger">{problem.detail}</Alert>}
      {guardado && !cambios && <Alert tone="success">Tus datos se guardaron.</Alert>}
      <dl className="grid gap-4 sm:grid-cols-2">
        <Dato label="Nombre y apellido">{perfil.full_name}</Dato>
        <Dato label="Correo electrónico">{perfil.email}</Dato>
        <Dato label="CUIT">{perfil.cuit}</Dato>
        <Dato label="Roles">{user?.roles.map(roleLabel).join(', ') || 'Sin roles asignados'}</Dato>
      </dl>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="text-sm text-ink-muted">
          El nombre y el CUIT identifican tu cuenta: para cambiarlos pedíselo a la Caja.
        </p>
        <Button
          icon={Mail}
          onClick={() => {
            setCambiandoCorreo(true)
          }}
        >
          Cambiar el correo
        </Button>
      </div>
      {cambiandoCorreo && (
        <CambioCorreoDialog
          actual={perfil.email}
          onClose={() => {
            setCambiandoCorreo(false)
          }}
        />
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Teléfono (opcional)"
          type="tel"
          inputMode="tel"
          value={telefono}
          maxLength={30}
          autoComplete="tel"
          hint="Con la característica, por ejemplo 264 427-6426."
          error={(telefono.trim() && invalido) || problem?.fieldErrors.phone_number}
          onChange={(e) => {
            // Solo números y separadores: letras y símbolos no entran.
            setTelefono(e.target.value.replace(NO_TELEFONO, ''))
          }}
        />
      </div>
      <div>
        <Button
          type="submit"
          variant="primary"
          icon={Save}
          busy={guardar.isPending}
          busyLabel="Guardando…"
          disabled={!cambios || Boolean(invalido)}
        >
          Guardar cambios
        </Button>
      </div>
    </form>
  )
}

export function PerfilPanel() {
  const perfil = useQuery({ queryKey: PERFIL_KEY, queryFn: fetchPerfil })
  return (
    <Panel title="Perfil" description="Tus datos de contacto en la Suite.">
      {perfil.isPending && (
        <div aria-busy="true" className="m-5 h-32 animate-pulse rounded-control bg-brand-50" />
      )}
      {perfil.isError && (
        <div className="px-5 py-5 sm:px-6">
          <Alert tone="danger">{toProblem(perfil.error).detail}</Alert>
        </div>
      )}
      {perfil.data && <FormPerfil perfil={perfil.data} />}
    </Panel>
  )
}

export function ContrasenaPanel() {
  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  const [repetida, setRepetida] = useState('')
  const [mensaje, setMensaje] = useState<string | null>(null)
  const checks = checkPasswordPolicy(nueva)
  const politicaOk = checks.every((c) => c.ok)
  const distintas = repetida.length > 0 && repetida !== nueva
  const cambio = useMutation({
    mutationFn: () => cambiarContrasena(actual, nueva),
    onSuccess: (texto) => {
      setMensaje(texto)
      setActual('')
      setNueva('')
      setRepetida('')
    },
  })
  const problem = cambio.isError ? toProblem(cambio.error) : null
  const enviar = (e: SyntheticEvent) => {
    e.preventDefault()
    setMensaje(null)
    cambio.mutate()
  }

  return (
    <Panel
      title="Contraseña"
      description="Al cambiarla cerramos tu sesión en los demás dispositivos y te avisamos por correo."
    >
      <form onSubmit={enviar} className="grid max-w-xl gap-4 px-5 py-5 sm:px-6" noValidate>
        {mensaje && <Alert tone="success">{mensaje}</Alert>}
        {problem && <Alert tone="danger">{problem.detail}</Alert>}
        <PasswordField
          label="Contraseña actual"
          name="current-password"
          value={actual}
          autoComplete="current-password"
          required
          onChange={(e) => {
            setActual(e.target.value)
          }}
        />
        <PasswordField
          label="Contraseña nueva"
          name="new-password"
          value={nueva}
          autoComplete="new-password"
          required
          hint={<RequisitosClave checks={checks} />}
          onChange={(e) => {
            setNueva(e.target.value)
          }}
        />
        <PasswordField
          label="Repetí la contraseña nueva"
          name="confirm-password"
          value={repetida}
          autoComplete="new-password"
          required
          error={distintas ? 'Las contraseñas no coinciden.' : undefined}
          onChange={(e) => {
            setRepetida(e.target.value)
          }}
        />
        <div>
          <Button
            type="submit"
            variant="primary"
            icon={KeyRound}
            busy={cambio.isPending}
            busyLabel="Cambiando…"
            disabled={!actual || !politicaOk || repetida !== nueva}
          >
            Cambiar contraseña
          </Button>
        </div>
      </form>
    </Panel>
  )
}
