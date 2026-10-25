import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Ban, RotateCcw, Save, UserPlus } from 'lucide-react'
import { useId, useState, type SyntheticEvent } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { toProblem } from '../../lib/api'
import { createUser, setUserRoles, setUserStatus, type RoleInfo, type UserRow } from './api'
import { RoleCheckboxes } from './RoleCheckboxes'

const USERS_KEY = ['users'] as const

export function CreateUserDialog({
  open,
  onClose,
  roles,
}: {
  open: boolean
  onClose: () => void
  roles: RoleInfo[]
}) {
  const queryClient = useQueryClient()
  const formId = useId()
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [cuit, setCuit] = useState('')
  const [phone, setPhone] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const reset = () => {
    setEmail('')
    setFullName('')
    setCuit('')
    setPhone('')
    setSelected([])
  }
  const create = useMutation({
    mutationFn: () =>
      createUser({
        email: email.trim(),
        full_name: fullName.trim(),
        cuit: cuit.trim(),
        phone_number: phone.trim() || null,
        roles: selected,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: USERS_KEY })
      reset()
      onClose()
    },
  })
  const problem = create.isError ? toProblem(create.error) : null
  const onSubmit = (event: SyntheticEvent) => {
    event.preventDefault()
    create.mutate()
  }

  return (
    <Dialog
      open={open}
      onClose={() => {
        create.reset()
        onClose()
      }}
      title="Nuevo usuario"
      description="La persona recibe un correo para definir su contraseña."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            type="submit"
            form={formId}
            variant="primary"
            icon={UserPlus}
            busy={create.isPending}
            busyLabel="Creando…"
            disabled={!email || !fullName || !cuit || selected.length === 0}
          >
            Crear y enviar correo
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={onSubmit} className="space-y-4" noValidate>
        {problem && Object.keys(problem.fieldErrors).length === 0 && (
          <Alert tone="danger">{problem.detail}</Alert>
        )}
        <Field
          label="Nombre y apellido"
          value={fullName}
          onChange={(e) => {
            setFullName(e.target.value)
          }}
          autoComplete="off"
          error={problem?.fieldErrors.full_name}
          required
        />
        <Field
          label="Correo electrónico"
          type="email"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
          }}
          autoComplete="off"
          autoCapitalize="none"
          error={problem?.fieldErrors.email}
          required
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="CUIT"
            value={cuit}
            onChange={(e) => {
              setCuit(e.target.value)
            }}
            inputMode="numeric"
            placeholder="20-12345678-9"
            autoComplete="off"
            error={problem?.fieldErrors.cuit}
            className="[&_input]:tabular-nums"
            required
          />
          <Field
            label="Teléfono (opcional)"
            type="tel"
            value={phone}
            onChange={(e) => {
              setPhone(e.target.value)
            }}
            autoComplete="off"
          />
        </div>
        <RoleCheckboxes roles={roles} selected={selected} onChange={setSelected} />
      </form>
    </Dialog>
  )
}

export function StatusDialog({ user, onClose }: { user: UserRow | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const suspending = user?.is_active ?? false
  const change = useMutation({
    mutationFn: () => setUserStatus(user?.id ?? '', !suspending, reason.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: USERS_KEY })
      setReason('')
      onClose()
    },
  })
  const problem = change.isError ? toProblem(change.error) : null

  return (
    <Dialog
      open={user !== null}
      onClose={() => {
        change.reset()
        setReason('')
        onClose()
      }}
      title={
        suspending ? `Suspender a ${user?.full_name ?? ''}` : `Reactivar a ${user?.full_name ?? ''}`
      }
      description={
        suspending
          ? 'La cuenta no podrá ingresar y se cierran sus sesiones abiertas. No se borra ningún dato.'
          : 'La cuenta vuelve a poder ingresar con su contraseña actual.'
      }
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant={suspending ? 'danger' : 'primary'}
            icon={suspending ? Ban : RotateCcw}
            busy={change.isPending}
            busyLabel={suspending ? 'Suspendiendo…' : 'Reactivando…'}
            disabled={reason.trim().length < 5}
            onClick={() => {
              change.mutate()
            }}
          >
            {suspending ? 'Suspender cuenta' : 'Reactivar cuenta'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {problem && <Alert tone="danger">{problem.detail}</Alert>}
        <Field
          label="Motivo"
          value={reason}
          onChange={(e) => {
            setReason(e.target.value)
          }}
          hint="Queda registrado en la auditoría. Mínimo 5 caracteres."
          maxLength={500}
          required
        />
      </div>
    </Dialog>
  )
}

export function RolesDialog({
  user,
  roles,
  onClose,
}: {
  user: UserRow | null
  roles: RoleInfo[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string[] | null>(null)
  const current = selected ?? user?.roles ?? []
  const save = useMutation({
    mutationFn: () => setUserRoles(user?.id ?? '', current),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: USERS_KEY })
      setSelected(null)
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null

  return (
    <Dialog
      open={user !== null}
      onClose={() => {
        save.reset()
        setSelected(null)
        onClose()
      }}
      title={`Roles de ${user?.full_name ?? ''}`}
      description="Los permisos cambian en la próxima acción de la persona, sin cerrar su sesión."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Guardando…"
            onClick={() => {
              save.mutate()
            }}
          >
            Guardar roles
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {problem && <Alert tone="danger">{problem.detail}</Alert>}
        <RoleCheckboxes roles={roles} selected={current} onChange={setSelected} />
      </div>
    </Dialog>
  )
}
