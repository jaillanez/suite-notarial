import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus } from 'lucide-react'
import { useState } from 'react'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { formatDate } from '../padron/labels'
import { actualizarAutoridad, crearAutoridad, fetchAutoridades, type Autoridad } from './api'

function AutoridadDialog({
  autoridad,
  open,
  onClose,
}: {
  autoridad?: Autoridad
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    cargo: autoridad?.cargo ?? '',
    nombre: autoridad?.nombre ?? '',
    orden: String(autoridad?.orden ?? 0),
    mandato_desde: autoridad?.mandato_desde ?? '',
    mandato_hasta: autoridad?.mandato_hasta ?? '',
    is_active: autoridad?.is_active ?? true,
  })
  const save = useMutation({
    mutationFn: () => {
      const data = {
        cargo: form.cargo.trim(),
        nombre: form.nombre.trim(),
        orden: Number.parseInt(form.orden, 10) || 0,
        mandato_desde: form.mandato_desde || null,
        mandato_hasta: form.mandato_hasta || null,
      }
      return autoridad
        ? actualizarAutoridad(autoridad.id, { ...data, is_active: form.is_active })
        : crearAutoridad(data)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['cms', 'autoridades'] })
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const bind = (key: 'cargo' | 'nombre' | 'orden' | 'mandato_desde' | 'mandato_hasta') => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) => {
      setForm((f) => ({ ...f, [key]: e.target.value }))
    },
    error: problem?.fieldErrors[key],
  })
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={autoridad ? 'Editar autoridad' : 'Nueva autoridad'}
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            busy={save.isPending}
            busyLabel="Guardando…"
            disabled={form.cargo.trim().length < 2 || form.nombre.trim().length < 2}
            onClick={() => {
              save.mutate()
            }}
          >
            Guardar
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {problem && (
          <div className="sm:col-span-2">
            <Alert tone="danger">{problem.detail}</Alert>
          </div>
        )}
        <Field label="Cargo" placeholder="Presidente" maxLength={100} {...bind('cargo')} />
        <Field label="Nombre" maxLength={150} {...bind('nombre')} />
        <Field label="Mandato desde (opcional)" type="date" {...bind('mandato_desde')} />
        <Field label="Mandato hasta (opcional)" type="date" {...bind('mandato_hasta')} />
        <Field
          label="Orden"
          inputMode="numeric"
          hint="Menor número, más arriba en el sitio."
          {...bind('orden')}
        />
        {autoridad && (
          <label className="flex min-h-11 cursor-pointer items-center gap-3 self-end text-sm text-ink">
            <input
              type="checkbox"
              className="size-4 accent-brand-800"
              checked={form.is_active}
              onChange={(e) => {
                setForm((f) => ({ ...f, is_active: e.target.checked }))
              }}
            />
            Visible en el sitio (desmarcar es la baja)
          </label>
        )}
      </div>
    </Dialog>
  )
}

export function AutoridadesAdmin() {
  const query = useQuery({ queryKey: ['cms', 'autoridades'], queryFn: fetchAutoridades })
  const [editando, setEditando] = useState<{ open: boolean; item?: Autoridad }>({ open: false })
  return (
    <Panel
      title="Autoridades"
      description="Se muestran en el sitio en el orden indicado. No se borran: se dan de baja."
      actions={
        <Button
          variant="primary"
          icon={Plus}
          onClick={() => {
            setEditando({ open: true })
          }}
        >
          Nueva autoridad
        </Button>
      }
    >
      {query.isError && (
        <div className="px-5 py-4 sm:px-6">
          <Alert tone="danger">{toProblem(query.error).detail}</Alert>
        </div>
      )}
      <ul className="divide-y divide-line">
        {query.data?.length === 0 && (
          <li className="px-5 py-10 text-center text-ink-muted sm:px-6">
            Todavía no hay autoridades cargadas.
          </li>
        )}
        {query.data?.map((a) => (
          <li
            key={a.id}
            className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 sm:px-6"
          >
            <div className="flex min-w-0 items-baseline gap-4">
              <span className="w-6 shrink-0 text-right text-sm text-ink-muted tabular-nums">
                {a.orden}
              </span>
              <span className="min-w-0">
                <span className="block font-semibold text-ink">{a.nombre}</span>
                <span className="block text-sm text-ink-muted tabular-nums">
                  {a.cargo}
                  {a.mandato_desde && ` · Desde ${formatDate(a.mandato_desde)}`}
                  {a.mandato_hasta && ` · Hasta ${formatDate(a.mandato_hasta)}`}
                </span>
              </span>
            </div>
            <div className="flex items-center gap-2">
              {!a.is_active && <StatusIndicator tone="unknown" label="De baja" />}
              <Button
                variant="ghost"
                icon={Pencil}
                onClick={() => {
                  setEditando({ open: true, item: a })
                }}
              >
                Editar
              </Button>
            </div>
          </li>
        ))}
      </ul>
      <AutoridadDialog
        key={editando.item?.id ?? `nueva-${String(editando.open)}`}
        autoridad={editando.item}
        open={editando.open}
        onClose={() => {
          setEditando({ open: false })
        }}
      />
    </Panel>
  )
}
