import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronRight, Search, UserPlus } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { Link } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Field } from '../../components/ui/Field'
import { Pagination } from '../../components/ui/Pagination'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import { useSession } from '../auth/session'
import { fetchDepartamentos, fetchEscribanos, type EscribanoFilters } from './api'
import { CARGO, ESTADO_MATRICULA } from './labels'

const PAGE_SIZE = 20

export function EscribanosPage() {
  const { can } = useSession()
  const [filters, setFilters] = useState<EscribanoFilters>({
    page: 1,
    pageSize: PAGE_SIZE,
    q: '',
    estado: '',
    registroNumero: '',
    departamento: '',
  })
  const deferred = useDeferredValue(filters)
  const query = useQuery({
    queryKey: ['padron', 'escribanos', deferred],
    queryFn: () => fetchEscribanos(deferred),
    placeholderData: keepPreviousData,
  })
  const departamentos = useQuery({
    queryKey: ['padron', 'departamentos'],
    queryFn: fetchDepartamentos,
    staleTime: Infinity,
  })
  const set = (patch: Partial<EscribanoFilters>) => {
    setFilters((f) => ({ ...f, ...patch, page: 'page' in patch ? (patch.page ?? 1) : 1 }))
  }
  const rows = query.data?.items ?? []
  const filtered = filters.q || filters.estado || filters.registroNumero || filters.departamento
  const empty = filtered
    ? 'Ningún escribano coincide con los filtros. Probá con el apellido, el CUIT o la matrícula.'
    : 'Todavía no hay escribanos en el padrón.'

  return (
    <>
      <PageHeader
        title="Escribanos"
        description="Padrón de escribanos matriculados. Las bajas son cambios de estado con motivo: ningún dato se borra."
      />
      <Panel
        title="Padrón"
        actions={
          can('escribanos:write') ? (
            <Link
              to="/padron/escribanos/nuevo"
              className="inline-flex min-h-11 items-center gap-2 rounded-control border border-brand-800 bg-brand-800 px-4 text-sm font-semibold text-white no-underline transition-colors duration-150 ease-out-quint hover:bg-brand-700"
            >
              <UserPlus aria-hidden="true" className="size-4" strokeWidth={2.25} />
              Nuevo escribano
            </Link>
          ) : undefined
        }
      >
        <div className="grid grid-cols-2 gap-4 border-b border-line px-5 py-4 sm:px-6 lg:grid-cols-[1fr_11rem_9rem_12rem]">
          <Field
            className="col-span-2 lg:col-span-1"
            label="Buscar"
            type="search"
            placeholder="Apellido, CUIT, DNI o matrícula"
            value={filters.q}
            onChange={(e) => {
              set({ q: e.target.value })
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
            label="Estado"
            value={filters.estado}
            onChange={(e) => {
              set({ estado: e.target.value as EscribanoFilters['estado'] })
            }}
            options={[
              { value: '', label: 'Todos' },
              ...Object.entries(ESTADO_MATRICULA).map(([value, { label }]) => ({ value, label })),
            ]}
          />
          <Field
            label="Registro Nº"
            inputMode="numeric"
            value={filters.registroNumero}
            onChange={(e) => {
              set({ registroNumero: e.target.value.replace(/\D/g, '') })
            }}
            className="[&_input]:tabular-nums"
          />
          <Select
            className="col-span-2 lg:col-span-1"
            label="Departamento"
            value={filters.departamento}
            onChange={(e) => {
              set({ departamento: e.target.value })
            }}
            options={[
              { value: '', label: 'Todos' },
              ...(departamentos.data ?? []).map((d) => ({ value: d, label: d })),
            ]}
          />
        </div>

        {query.isError && (
          <div className="px-5 py-4 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}

        <ul className="divide-y divide-line sm:hidden" aria-busy={query.isFetching}>
          {!query.isPending && rows.length === 0 && (
            <li className="px-5 py-10 text-center text-ink-muted">{empty}</li>
          )}
          {rows.map((row) => (
            <li key={row.id}>
              <Link
                to={`/padron/escribanos/${row.id}`}
                className="block px-5 py-4 text-ink no-underline hover:bg-brand-50"
              >
                <span className="flex items-start justify-between gap-3">
                  <span className="min-w-0">
                    <span className="block font-semibold">{row.apellido_nombre}</span>
                    <span className="block text-sm text-ink-muted tabular-nums">
                      Mat. {row.matricula_numero} · {row.cuit}
                    </span>
                  </span>
                  <StatusIndicator
                    tone={ESTADO_MATRICULA[row.estado_matricula].tone}
                    label={ESTADO_MATRICULA[row.estado_matricula].label}
                  />
                </span>
                <span className="mt-1 block text-sm text-ink-muted">
                  {row.registro_actual && row.cargo_actual
                    ? `${CARGO[row.cargo_actual]} · Registro ${String(row.registro_actual)}`
                    : 'Sin cargo vigente'}
                </span>
              </Link>
            </li>
          ))}
        </ul>

        <div className="hidden max-h-[40rem] overflow-auto sm:block" aria-busy={query.isFetching}>
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">Padrón de escribanos</caption>
            <thead className="sticky top-0 z-10 bg-surface-sunken text-xs font-semibold text-ink-muted">
              <tr className="border-b border-line">
                <th scope="col" className="w-24 px-5 py-3 sm:px-6">
                  Matrícula
                </th>
                <th scope="col" className="px-3 py-3">
                  Escribano
                </th>
                <th scope="col" className="px-3 py-3">
                  Cargo vigente
                </th>
                <th scope="col" className="px-3 py-3">
                  Estado
                </th>
                <th scope="col" className="w-12 px-5 py-3 sm:px-6">
                  <span className="sr-only">Abrir ficha</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {query.isPending &&
                Array.from({ length: 6 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={5} className="px-5 py-4 sm:px-6">
                      <span className="block h-5 w-full animate-pulse rounded-control bg-brand-50" />
                    </td>
                  </tr>
                ))}
              {!query.isPending && rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-5 py-10 text-center text-ink-muted sm:px-6">
                    {empty}
                  </td>
                </tr>
              )}
              {rows.map((row) => (
                <tr key={row.id} className="group hover:bg-brand-50">
                  <td className="px-5 py-3 font-semibold text-ink tabular-nums sm:px-6">
                    {row.matricula_numero}
                  </td>
                  <td className="px-3 py-3">
                    <Link
                      to={`/padron/escribanos/${row.id}`}
                      className="font-semibold text-brand-800 no-underline group-hover:underline"
                    >
                      {row.apellido_nombre}
                    </Link>
                    <span className="block text-ink-muted tabular-nums">
                      {row.cuit} · DNI {row.numero_documento}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-ink">
                    {row.registro_actual && row.cargo_actual ? (
                      <>
                        {CARGO[row.cargo_actual]}
                        <span className="block text-ink-muted tabular-nums">
                          Registro {row.registro_actual}
                        </span>
                      </>
                    ) : (
                      <span className="text-ink-subtle">Sin cargo vigente</span>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    <StatusIndicator
                      tone={ESTADO_MATRICULA[row.estado_matricula].tone}
                      label={ESTADO_MATRICULA[row.estado_matricula].label}
                    />
                  </td>
                  <td className="px-5 py-3 text-right sm:px-6">
                    <ChevronRight
                      aria-hidden="true"
                      className="inline size-5 text-ink-subtle group-hover:text-brand-800"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination
          page={filters.page}
          pageSize={filters.pageSize}
          total={query.data?.total ?? 0}
          onPage={(page) => {
            set({ page })
          }}
        />
      </Panel>
    </>
  )
}
