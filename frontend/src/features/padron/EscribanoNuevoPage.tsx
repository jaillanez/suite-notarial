import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { useState, type SyntheticEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { createEscribano } from './api'

const EMPTY = {
  cuit: '',
  tipo_documento: 'DNI',
  numero_documento: '',
  apellido: '',
  nombre: '',
  fecha_nacimiento: '',
  email: '',
  telefono: '',
  domicilio_real: '',
  matricula_numero: '',
  tomo: '',
  folio: '',
  fecha_matriculacion: '',
}

const orNull = (value: string): string | null => (value.trim() ? value.trim() : null)

export function EscribanoNuevoPage() {
  const [form, setForm] = useState(EMPTY)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const create = useMutation({
    mutationFn: () =>
      createEscribano({
        persona: {
          cuit: form.cuit.trim(),
          tipo_documento: form.tipo_documento,
          numero_documento: form.numero_documento.trim(),
          apellido: form.apellido.trim(),
          nombre: form.nombre.trim(),
          fecha_nacimiento: orNull(form.fecha_nacimiento),
          email: orNull(form.email),
          telefono: orNull(form.telefono),
          domicilio_real: orNull(form.domicilio_real),
        },
        matricula_numero: Number(form.matricula_numero),
        tomo: orNull(form.tomo),
        folio: orNull(form.folio),
        fecha_matriculacion: form.fecha_matriculacion,
      }),
    onSuccess: async (escribano) => {
      await queryClient.invalidateQueries({ queryKey: ['padron'] })
      void navigate(`/padron/escribanos/${escribano.id}`, { replace: true })
    },
  })
  const problem = create.isError ? toProblem(create.error) : null
  const err = (field: string) => problem?.fieldErrors[field]
  const bind = (key: keyof typeof EMPTY) => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) => {
      setForm((f) => ({ ...f, [key]: e.target.value }))
    },
  })
  const ready =
    form.cuit &&
    form.numero_documento &&
    form.apellido &&
    form.nombre &&
    form.matricula_numero &&
    form.fecha_matriculacion

  const onSubmit = (event: SyntheticEvent) => {
    event.preventDefault()
    create.mutate()
  }

  return (
    <>
      <PageHeader
        title="Nuevo escribano"
        description="Alta en el padrón con sus datos personales y su matrícula. El cargo en un registro se asigna después, desde la ficha."
      />
      <form onSubmit={onSubmit} noValidate className="space-y-6">
        {problem && Object.keys(problem.fieldErrors).length === 0 && (
          <Alert tone="danger">{problem.detail}</Alert>
        )}
        <Panel title="Datos personales">
          <div className="grid gap-5 px-5 py-5 sm:grid-cols-2 sm:px-6">
            <Field
              label="Apellido"
              autoComplete="off"
              required
              error={err('apellido')}
              {...bind('apellido')}
            />
            <Field
              label="Nombre"
              autoComplete="off"
              required
              error={err('nombre')}
              {...bind('nombre')}
            />
            <Field
              label="CUIT"
              inputMode="numeric"
              placeholder="20-12345678-9"
              required
              error={err('cuit')}
              hint="Se valida con el dígito verificador de AFIP."
              className="[&_input]:tabular-nums"
              {...bind('cuit')}
            />
            <div className="grid grid-cols-[8rem_1fr] gap-3">
              <Select
                label="Documento"
                options={['DNI', 'LC', 'LE', 'PASAPORTE'].map((v) => ({ value: v, label: v }))}
                {...bind('tipo_documento')}
              />
              <Field
                label="Número"
                inputMode="numeric"
                required
                error={err('numero_documento')}
                className="[&_input]:tabular-nums"
                {...bind('numero_documento')}
              />
            </div>
            <Field
              label="Fecha de nacimiento"
              type="date"
              error={err('fecha_nacimiento')}
              {...bind('fecha_nacimiento')}
            />
            <Field label="Teléfono" type="tel" autoComplete="off" {...bind('telefono')} />
            <Field
              label="Correo electrónico"
              type="email"
              autoComplete="off"
              hint="Necesario para crearle la cuenta de autogestión."
              error={err('email')}
              className="sm:col-span-2"
              {...bind('email')}
            />
            <TextArea
              label="Domicilio real"
              rows={2}
              className="sm:col-span-2"
              {...bind('domicilio_real')}
            />
          </div>
        </Panel>
        <Panel title="Matrícula">
          <div className="grid gap-5 px-5 py-5 sm:grid-cols-4 sm:px-6">
            <Field
              label="Número de matrícula"
              inputMode="numeric"
              required
              error={err('matricula_numero')}
              className="sm:col-span-2 [&_input]:tabular-nums"
              {...bind('matricula_numero')}
            />
            <Field label="Tomo" autoComplete="off" {...bind('tomo')} />
            <Field label="Folio" autoComplete="off" {...bind('folio')} />
            <Field
              label="Fecha de matriculación"
              type="date"
              required
              error={err('fecha_matriculacion')}
              className="sm:col-span-2"
              {...bind('fecha_matriculacion')}
            />
          </div>
        </Panel>
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Link
            to="/padron/escribanos"
            className="inline-flex min-h-11 items-center justify-center rounded-control border border-line-strong bg-surface px-4 text-sm font-semibold text-brand-800 no-underline hover:bg-brand-50"
          >
            Cancelar
          </Link>
          <Button
            type="submit"
            variant="primary"
            icon={Save}
            busy={create.isPending}
            busyLabel="Guardando…"
            disabled={!ready}
          >
            Dar de alta
          </Button>
        </div>
      </form>
    </>
  )
}
