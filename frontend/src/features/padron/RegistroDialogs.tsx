import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { useState } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import {
  closeRegistro,
  createCircunscripcion,
  createRegistro,
  fetchCircunscripciones,
  fetchDepartamentos,
  updateCircunscripcion,
  updateRegistro,
  type Circunscripcion,
  type Registro,
} from './api'

const orNull = (value: string): string | null => (value.trim() ? value.trim() : null)

export function RegistroFormDialog({
  open,
  onClose,
  registro,
}: {
  open: boolean
  onClose: () => void
  registro?: Registro
}) {
  const queryClient = useQueryClient()
  const circunscripciones = useQuery({
    queryKey: ['padron', 'circunscripciones'],
    queryFn: fetchCircunscripciones,
    enabled: open,
  })
  const departamentos = useQuery({
    queryKey: ['padron', 'departamentos'],
    queryFn: fetchDepartamentos,
    staleTime: Infinity,
    enabled: open,
  })
  const activas = (circunscripciones.data ?? []).filter(
    (c) => c.is_active || c.id === registro?.circunscripcion.id,
  )
  const [form, setForm] = useState({
    numero_registro: registro ? String(registro.numero_registro) : '',
    nombre_fantasia: registro?.nombre_fantasia ?? '',
    circunscripcion_id: registro?.circunscripcion.id ?? '',
    departamento: registro?.departamento ?? 'Capital',
    domicilio_legal: registro?.domicilio_legal ?? '',
    telefono: registro?.telefono ?? '',
    email: registro?.email ?? '',
    fecha_creacion: registro?.fecha_creacion ?? '',
  })
  const circunscripcionId = form.circunscripcion_id || activas[0]?.id || ''
  const save = useMutation({
    mutationFn: () => {
      const data = {
        nombre_fantasia: orNull(form.nombre_fantasia),
        circunscripcion_id: circunscripcionId,
        departamento: form.departamento,
        domicilio_legal: form.domicilio_legal.trim(),
        telefono: orNull(form.telefono),
        email: orNull(form.email),
        fecha_creacion: orNull(form.fecha_creacion),
      }
      return registro
        ? updateRegistro(registro.id, data)
        : createRegistro({ ...data, numero_registro: Number(form.numero_registro) })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['padron'] })
      if (registro) await queryClient.invalidateQueries({ queryKey: ['registro', registro.id] })
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const bind = (key: keyof typeof form) => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) => {
      setForm((f) => ({ ...f, [key]: e.target.value }))
    },
    error: problem?.fieldErrors[key],
  })
  const ready =
    circunscripcionId && form.domicilio_legal.trim() && (registro || form.numero_registro)

  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={
        registro ? `Editar Registro ${String(registro.numero_registro)}` : 'Nuevo registro notarial'
      }
      description={
        registro
          ? 'El número de registro no se modifica.'
          : 'El registro nace vacante y pasa a activo al designar a su titular.'
      }
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Guardando…"
            disabled={!ready}
            onClick={() => {
              save.mutate()
            }}
          >
            {registro ? 'Guardar cambios' : 'Crear registro'}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {problem && Object.keys(problem.fieldErrors).length === 0 && (
          <div className="sm:col-span-2">
            <Alert tone="danger">{problem.detail}</Alert>
          </div>
        )}
        {activas.length === 0 && circunscripciones.isSuccess && (
          <div className="sm:col-span-2">
            <Alert tone="warning">Primero cargá al menos una circunscripción.</Alert>
          </div>
        )}
        {!registro && (
          <Field
            label="Número de registro"
            inputMode="numeric"
            className="[&_input]:tabular-nums"
            {...bind('numero_registro')}
          />
        )}
        <Field label="Nombre de fantasía (opcional)" {...bind('nombre_fantasia')} />
        <Select
          label="Circunscripción"
          value={circunscripcionId}
          onChange={(e) => {
            setForm((f) => ({ ...f, circunscripcion_id: e.target.value }))
          }}
          options={activas.map((c) => ({ value: c.id, label: c.nombre }))}
        />
        <Select
          label="Departamento"
          value={form.departamento}
          onChange={(e) => {
            setForm((f) => ({ ...f, departamento: e.target.value }))
          }}
          options={(departamentos.data ?? [form.departamento]).map((d) => ({ value: d, label: d }))}
        />
        <TextArea
          label="Domicilio legal"
          rows={2}
          className="sm:col-span-2"
          {...bind('domicilio_legal')}
        />
        <Field label="Teléfono" type="tel" {...bind('telefono')} />
        <Field label="Correo de la oficina" type="email" {...bind('email')} />
        <Field label="Fecha de creación (opcional)" type="date" {...bind('fecha_creacion')} />
      </div>
    </Dialog>
  )
}

export function CerrarRegistroDialog({
  registro,
  open,
  onClose,
}: {
  registro: Registro
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [motivo, setMotivo] = useState('')
  const save = useMutation({
    mutationFn: () => closeRegistro(registro.id, motivo.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['padron'] })
      await queryClient.invalidateQueries({ queryKey: ['registro', registro.id] })
      onClose()
    },
  })
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={`Cerrar el Registro ${String(registro.numero_registro)}`}
      description="Un registro cerrado no admite cargos ni cambios. Requiere que no tenga cargos vigentes."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="danger"
            busy={save.isPending}
            busyLabel="Cerrando…"
            disabled={motivo.trim().length < 5}
            onClick={() => {
              save.mutate()
            }}
          >
            Cerrar registro
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <TextArea
          label="Motivo"
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
          hint="Obligatorio. Queda registrado en la auditoría."
        />
      </div>
    </Dialog>
  )
}

export function CircunscripcionDialog({
  open,
  onClose,
  item,
}: {
  open: boolean
  onClose: () => void
  item?: Circunscripcion
}) {
  const queryClient = useQueryClient()
  const [nombre, setNombre] = useState(item?.nombre ?? '')
  const [descripcion, setDescripcion] = useState(item?.descripcion ?? '')
  const [activa, setActiva] = useState(item?.is_active ?? true)
  const save = useMutation({
    mutationFn: () =>
      item
        ? updateCircunscripcion(item.id, {
            nombre: nombre.trim(),
            descripcion: orNull(descripcion),
            is_active: activa,
          })
        : createCircunscripcion(nombre.trim(), orNull(descripcion)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['padron', 'circunscripciones'] })
      onClose()
    },
  })
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={item ? 'Editar circunscripción' : 'Nueva circunscripción'}
      description="Las circunscripciones no se borran: se desactivan."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Guardando…"
            disabled={nombre.trim().length < 2}
            onClick={() => {
              save.mutate()
            }}
          >
            Guardar
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <Field
          label="Nombre"
          value={nombre}
          onChange={(e) => {
            setNombre(e.target.value)
          }}
        />
        <TextArea
          label="Descripción (opcional)"
          rows={2}
          value={descripcion}
          onChange={(e) => {
            setDescripcion(e.target.value)
          }}
        />
        {item && (
          <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm font-medium text-ink">
            <input
              type="checkbox"
              checked={activa}
              onChange={(e) => {
                setActiva(e.target.checked)
              }}
              className="size-5 cursor-pointer accent-brand-800"
            />
            Activa (disponible para nuevos registros)
          </label>
        )}
      </div>
    </Dialog>
  )
}
