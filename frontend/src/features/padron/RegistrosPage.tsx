import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronRight, Plus, Search } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { Link } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { Pagination } from '../../components/ui/Pagination'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import { useSession } from '../auth/session'
import {
  fetchCircunscripciones,
  fetchDepartamentos,
  fetchRegistros,
  type Circunscripcion,
  type EstadoRegistro,
} from './api'
import { ESTADO_REGISTRO } from './labels'
import { CircunscripcionDialog, RegistroFormDialog } from './RegistroDialogs'

const PAGE_SIZE = 20

export function RegistrosPage() {
  const { can } = useSession()
  const canWrite = can('escribanos:write')
  const [filters, setFilters] = useState({
    page: 1,
    q: '',
    departamento: '',
    estado: '' as EstadoRegistro | '',
  })
  const deferred = useDeferredValue(filters)
  const query = useQuery({
    queryKey: ['padron', 'registros', deferred],
    queryFn: () => fetchRegistros({ ...deferred, pageSize: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const departamentos = useQuery({
    queryKey: ['padron', 'departamentos'],
    queryFn: fetchDepartamentos,
    staleTime: Infinity,
  })
  const circunscripciones = useQuery({
    queryKey: ['padron', 'circunscripciones'],
    queryFn: fetchCircunscripciones,
  })
  const [creating, setCreating] = useState(false)
  const [circDialog, setCircDialog] = useState<{ open: boolean; item?: Circunscripcion }>({
    open: false,
  })
  const rows = query.data?.items ?? []

  return (
    <>
      <PageHeader
        title="Registros notariales"
        description="Cada registro tiene un titular y puede tener adscriptos. Un registro sin titular figura como vacante."
      />
      <Panel
        title="Registros"
        actions={
          canWrite ? (
            <Button
              variant="primary"
              icon={Plus}
              onClick={() => {
                setCreating(true)
              }}
            >
              Nuevo registro
            </Button>
          ) : undefined
        }
      >
        <div className="grid gap-4 border-b border-line px-5 py-4 sm:grid-cols-[1fr_12rem_11rem] sm:px-6">
          <Field
            label="Buscar"
            type="search"
            placeholder="Número o nombre"
            value={filters.q}
            onChange={(e) => {
              setFilters((f) => ({ ...f, q: e.target.value, page: 1 }))
            }}
            trailing={
              <Search
                aria-hidden="true"
                className="mr-3 size-4 text-ink-subtle"
                strokeWidth={2.25}
              />
            }
          />
          <Select
            label="Departamento"
            value={filters.departamento}
            onChange={(e) => {
              setFilters((f) => ({ ...f, departamento: e.target.value, page: 1 }))
            }}
            options={[
              { value: '', label: 'Todos' },
              ...(departamentos.data ?? []).map((d) => ({ value: d, label: d })),
            ]}
          />
          <Select
            label="Estado"
            value={filters.estado}
            onChange={(e) => {
              setFilters((f) => ({ ...f, estado: e.target.value as EstadoRegistro | '', page: 1 }))
            }}
            options={[
              { value: '', label: 'Todos' },
              ...Object.entries(ESTADO_REGISTRO).map(([value, { label }]) => ({ value, label })),
            ]}
          />
        </div>
        {query.isError && (
          <div className="px-5 py-4 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}
        <ul className="divide-y divide-line" aria-busy={query.isFetching}>
          {query.isPending &&
            Array.from({ length: 4 }, (_, i) => (
              <li key={i} className="px-5 py-4 sm:px-6">
                <span className="block h-10 w-full animate-pulse rounded-control bg-brand-50" />
              </li>
            ))}
          {!query.isPending && rows.length === 0 && (
            <li className="px-5 py-10 text-center text-ink-muted sm:px-6">
              {filters.q || filters.departamento || filters.estado
                ? 'Ningún registro coincide con los filtros.'
                : 'Todavía no hay registros notariales cargados.'}
            </li>
          )}
          {rows.map((r) => (
            <li key={r.id}>
              <Link
                to={`/padron/registros/${r.id}`}
                className="group flex items-center gap-4 px-5 py-4 text-ink no-underline hover:bg-brand-50 sm:px-6"
              >
                <span className="w-14 shrink-0 text-2xl font-semibold text-brand-900 tabular-nums">
                  {r.numero_registro}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-brand-800 group-hover:underline">
                    {r.nombre_fantasia ?? `Registro ${String(r.numero_registro)}`}
                  </span>
                  <span className="block text-sm text-ink-muted">
                    {r.departamento} · {r.circunscripcion.nombre}
                  </span>
                  <span className="block text-sm text-ink">
                    {r.titular ? `Titular: ${r.titular.apellido_nombre}` : 'Sin titular'}
                    {r.cantidad_adscriptos > 0
                      ? ` · ${String(r.cantidad_adscriptos)} ${r.cantidad_adscriptos === 1 ? 'adscripto' : 'adscriptos'}`
                      : ''}
                  </span>
                </span>
                <StatusIndicator
                  tone={ESTADO_REGISTRO[r.estado].tone}
                  label={ESTADO_REGISTRO[r.estado].label}
                />
                <ChevronRight
                  aria-hidden="true"
                  className="hidden size-5 shrink-0 text-ink-subtle group-hover:text-brand-800 sm:block"
                />
              </Link>
            </li>
          ))}
        </ul>
        <Pagination
          page={filters.page}
          pageSize={PAGE_SIZE}
          total={query.data?.total ?? 0}
          onPage={(page) => {
            setFilters((f) => ({ ...f, page }))
          }}
        />
      </Panel>

      <Panel
        className="mt-6"
        title="Circunscripciones"
        description="Agrupan los registros por jurisdicción. No se borran: se desactivan."
        actions={
          canWrite ? (
            <Button
              icon={Plus}
              onClick={() => {
                setCircDialog({ open: true })
              }}
            >
              Nueva circunscripción
            </Button>
          ) : undefined
        }
      >
        {circunscripciones.data?.length === 0 ? (
          <p className="px-5 py-6 text-sm text-ink-muted sm:px-6">
            Todavía no hay circunscripciones. Cargá la primera para poder crear registros.
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {(circunscripciones.data ?? []).map((c) => (
              <li
                key={c.id}
                className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 sm:px-6"
              >
                <span className="min-w-0">
                  <span className="block font-semibold text-ink">{c.nombre}</span>
                  {c.descripcion && (
                    <span className="block text-sm text-ink-muted">{c.descripcion}</span>
                  )}
                </span>
                <span className="flex items-center gap-2">
                  {!c.is_active && <StatusIndicator tone="unknown" label="Inactiva" />}
                  {canWrite && (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setCircDialog({ open: true, item: c })
                      }}
                    >
                      Editar
                    </Button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <RegistroFormDialog
        key={`nuevo-${String(creating)}`}
        open={creating}
        onClose={() => {
          setCreating(false)
        }}
      />
      <CircunscripcionDialog
        key={circDialog.item?.id ?? `nueva-${String(circDialog.open)}`}
        open={circDialog.open}
        item={circDialog.item}
        onClose={() => {
          setCircDialog({ open: false })
        }}
      />
    </>
  )
}
