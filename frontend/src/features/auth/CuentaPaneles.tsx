import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Save } from 'lucide-react'
import { useState, type SyntheticEvent } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field, PasswordField } from '../../components/ui/Field'
import { Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { actualizarPerfil, cambiarContrasena, fetchPerfil, type Perfil } from './api'
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

function FormPerfil({ perfil }: { perfil: Perfil }) {
  const { user } = useSession()
  const queryClient = useQueryClient()
  const [telefono, setTelefono] = useState(perfil.phone_number ?? '')
  const [guardado, setGuardado] = useState(false)
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
  const enviar = (e: SyntheticEvent) => {
    e.preventDefault()
    setGuardado(false)
    guardar.mutate()
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
      <p className="text-sm text-ink-muted">
        El nombre, el correo y el CUIT identifican tu cuenta: para cambiarlos pedíselo a la Caja.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Teléfono (opcional)"
          type="tel"
          value={telefono}
          maxLength={50}
          autoComplete="tel"
          error={problem?.fieldErrors.phone_number}
          onChange={(e) => {
            setTelefono(e.target.value)
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
          disabled={!cambios}
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
