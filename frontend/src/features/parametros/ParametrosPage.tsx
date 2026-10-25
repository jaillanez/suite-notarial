import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Plus, Save } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { useSession } from '../auth/session'
import { formatDate, todayIso } from '../padron/labels'
import { createConcepto, fetchConceptos, type TipoConcepto } from './api'
import { TIPO, resumenValor } from './labels'

function NuevoConceptoDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [codigo, setCodigo] = useState('')
  const [nombre, setNombre] = useState('')
  const [tipo, setTipo] = useState<TipoConcepto>('PORCENTUAL_ACTO')
  const [descripcion, setDescripcion] = useState('')
  const save = useMutation({
    mutationFn: () =>
      createConcepto({
        codigo: codigo.trim().toUpperCase(),
        nombre: nombre.trim(),
        tipo,
        descripcion: descripcion.trim() || null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['parametros'] })
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Nuevo concepto"
      description="El concepto define qué se calcula. Sus valores se cargan después como vigencias, que aprueba otra persona."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Creando…"
            disabled={codigo.trim().length < 3 || nombre.trim().length < 3}
            onClick={() => {
              save.mutate()
            }}
          >
            Crear concepto
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {problem && Object.keys(problem.fieldErrors).length === 0 && (
          <Alert tone="danger">{problem.detail}</Alert>
        )}
        <Field
          label="Código"
          value={codigo}
          onChange={(e) => {
            setCodigo(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))
          }}
          hint="Mayúsculas y guiones bajos, por ejemplo APORTE_ESCRITURA. No se puede cambiar."
          error={problem?.fieldErrors.codigo}
          className="[&_input]:font-mono"
        />
        <Field
          label="Nombre"
          value={nombre}
          onChange={(e) => {
            setNombre(e.target.value)
          }}
          error={problem?.fieldErrors.nombre}
        />
        <Select
          label="Tipo"
          value={tipo}
          onChange={(e) => {
            setTipo(e.target.value as TipoConcepto)
          }}
          options={(Object.keys(TIPO) as TipoConcepto[]).map((t) => ({
            value: t,
            label: TIPO[t].label,
          }))}
        />
        <p className="text-sm text-ink-muted">{TIPO[tipo].ayuda}</p>
        <TextArea
          label="Descripción (opcional)"
          rows={2}
          value={descripcion}
          onChange={(e) => {
            setDescripcion(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

export function ParametrosPage() {
  const { can } = useSession()
  const [fecha, setFecha] = useState(todayIso())
  const [creating, setCreating] = useState(false)
  const query = useQuery({
    queryKey: ['parametros', 'conceptos', fecha],
    queryFn: () => fetchConceptos(fecha),
    enabled: /^\d{4}-\d{2}-\d{2}$/.test(fecha),
  })
  const conceptos = query.data ?? []
  const pendientes = conceptos.reduce((n, c) => n + c.pendientes, 0)
  const ejemplos = conceptos.filter((c) => c.vigente?.es_ejemplo)

  return (
    <>
      <PageHeader
        title="Parámetros previsionales"
        description="Alícuotas, montos fijos y tasas que usa el cálculo de boletas. Cada cambio es una vigencia nueva que aprueba otra persona; las anteriores nunca se modifican."
      />
      <div className="mb-6 space-y-4">
        {ejemplos.length > 0 && (
          <Alert tone="warning" title="Hay valores de ejemplo, no oficiales">
            {ejemplos.map((c) => c.codigo).join(', ')} se calculan con valores inventados para
            desarrollo. Antes de emitir boletas reales hay que cargar los valores aprobados por la
            Caja.
          </Alert>
        )}
        {pendientes > 0 && (
          <Alert
            tone="info"
            title={`${String(pendientes)} ${pendientes === 1 ? 'propuesta pendiente' : 'propuestas pendientes'} de aprobación`}
          >
            Abrí el concepto marcado para revisarla. La aprueba alguien distinto de quien la
            propuso.
          </Alert>
        )}
      </div>
      <Panel
        title="Conceptos"
        actions={
          can('parameters:write') ? (
            <Button
              variant="primary"
              icon={Plus}
              onClick={() => {
                setCreating(true)
              }}
            >
              Nuevo concepto
            </Button>
          ) : undefined
        }
      >
        <div className="border-b border-line px-5 py-4 sm:px-6">
          <Field
            label="Valores vigentes al"
            type="date"
            value={fecha}
            onChange={(e) => {
              setFecha(e.target.value)
            }}
            className="max-w-56"
          />
        </div>
        {query.isError && (
          <div className="px-5 py-4 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}
        <ul className="divide-y divide-line" aria-busy={query.isFetching}>
          {query.isPending &&
            Array.from({ length: 3 }, (_, i) => (
              <li key={i} className="px-5 py-4 sm:px-6">
                <span className="block h-10 w-full animate-pulse rounded-control bg-brand-50" />
              </li>
            ))}
          {query.isSuccess && conceptos.length === 0 && (
            <li className="px-5 py-10 text-center text-ink-muted sm:px-6">
              Todavía no hay conceptos. Creá el primero para cargar sus vigencias.
            </li>
          )}
          {conceptos.map((c) => (
            <li key={c.id}>
              <Link
                to={`/parametros/${c.id}`}
                className="group flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-4 text-ink no-underline hover:bg-brand-50 sm:flex-nowrap sm:px-6"
              >
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-brand-800 group-hover:underline">
                    {c.nombre}
                  </span>
                  <span className="block text-sm text-ink-muted">
                    <span className="font-mono">{c.codigo}</span> · {TIPO[c.tipo].label}
                    {!c.is_active && ' · inactivo'}
                  </span>
                </span>
                <span className="flex flex-wrap items-center gap-2 sm:justify-end">
                  {c.pendientes > 0 && (
                    <StatusIndicator
                      tone="warning"
                      label={`${String(c.pendientes)} pendiente${c.pendientes === 1 ? '' : 's'}`}
                    />
                  )}
                  {c.vigente?.es_ejemplo && <StatusIndicator tone="warning" label="Ejemplo" />}
                </span>
                <span className="w-full text-left sm:w-44 sm:text-right">
                  {c.vigente ? (
                    <>
                      <span className="block text-lg font-semibold text-ink tabular-nums">
                        {resumenValor(c.tipo, c.vigente)}
                      </span>
                      <span className="block text-xs text-ink-muted tabular-nums">
                        desde el {formatDate(c.vigente.fecha_desde)}
                      </span>
                    </>
                  ) : (
                    <span className="text-sm text-ink-subtle">Sin vigencia a esa fecha</span>
                  )}
                </span>
                <ChevronRight
                  aria-hidden="true"
                  className="hidden size-5 shrink-0 text-ink-subtle group-hover:text-brand-800 sm:block"
                />
              </Link>
            </li>
          ))}
        </ul>
      </Panel>
      <NuevoConceptoDialog
        key={String(creating)}
        open={creating}
        onClose={() => {
          setCreating(false)
        }}
      />
    </>
  )
}
