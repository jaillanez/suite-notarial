import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, Columns3, FileSpreadsheet, FileText, ShieldAlert, X } from 'lucide-react'
import { useDeferredValue, useId, useState } from 'react'
import { Link, useParams } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { Pagination } from '../../components/ui/Pagination'
import { Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import { formatPeriodo, ultimosPeriodos } from '../ddjj/labels'
import { todayIso } from '../padron/labels'
import {
  exportar,
  fetchPagina,
  fetchReportes,
  type Columna,
  type Filtro,
  type Reporte,
} from './api'
import { alineadaDerecha, formatCelda } from './formato'

const PAGE_SIZE = 25

function claveColumnas(codigo: string): string {
  return `suite:reporte:${codigo}:columnas`
}

/** Columnas elegidas por la persona, recordadas en este navegador (si se puede). */
function columnasIniciales(reporte: Reporte): string[] {
  try {
    const guardadas = localStorage.getItem(claveColumnas(reporte.codigo))
    if (guardadas) {
      const keys = JSON.parse(guardadas) as unknown
      if (Array.isArray(keys)) {
        const validas = reporte.columnas.map((c) => c.key)
        const elegidas = keys.filter(
          (k): k is string => typeof k === 'string' && validas.includes(k),
        )
        if (elegidas.length > 0) return elegidas
      }
    }
  } catch {
    // Sin almacenamiento disponible: se usan las columnas por defecto.
  }
  return reporte.columnas.filter((c) => c.visible).map((c) => c.key)
}

function FiltroControl({
  filtro,
  value,
  onChange,
}: {
  filtro: Filtro
  value: string
  onChange: (value: string) => void
}) {
  const change = (e: { target: { value: string } }) => {
    onChange(e.target.value)
  }
  if (filtro.tipo === 'PERIODO') {
    return (
      <Select
        label={filtro.label}
        value={value}
        onChange={change}
        options={[
          { value: '', label: 'Cualquiera' },
          ...ultimosPeriodos(todayIso(), 36).map((p) => ({ value: p, label: formatPeriodo(p) })),
        ]}
      />
    )
  }
  if (filtro.tipo === 'OPCIONES') {
    return (
      <Select
        label={filtro.label}
        value={value}
        onChange={change}
        options={[{ value: '', label: 'Todos' }, ...filtro.opciones]}
      />
    )
  }
  return (
    <Field
      label={filtro.label}
      type={filtro.tipo === 'FECHA' ? 'date' : filtro.tipo === 'TEXTO' ? 'search' : 'text'}
      inputMode={filtro.tipo === 'ENTERO' ? 'numeric' : undefined}
      hint={filtro.ayuda ?? undefined}
      className="[&_input]:tabular-nums"
      value={value}
      onChange={change}
    />
  )
}

function SelectorColumnas({
  reporte,
  elegidas,
  onChange,
}: {
  reporte: Reporte
  elegidas: string[]
  onChange: (keys: string[]) => void
}) {
  const [abierto, setAbierto] = useState(false)
  const regionId = useId()
  const toggle = (key: string) => {
    // Se respeta el orden del reporte; siempre queda al menos una columna.
    const next = elegidas.includes(key)
      ? elegidas.filter((k) => k !== key)
      : reporte.columnas.map((c) => c.key).filter((k) => k === key || elegidas.includes(k))
    if (next.length > 0) onChange(next)
  }
  return (
    <div className="border-b border-line px-5 py-3 sm:px-6">
      <Button
        variant="ghost"
        icon={abierto ? X : Columns3}
        aria-expanded={abierto}
        aria-controls={regionId}
        className="-ml-4"
        onClick={() => {
          setAbierto((v) => !v)
        }}
      >
        Columnas ({elegidas.length} de {reporte.columnas.length})
      </Button>
      <fieldset id={regionId} hidden={!abierto} className="mt-2">
        <legend className="sr-only">Columnas visibles</legend>
        <p className="text-sm text-ink-muted">
          Elegí qué columnas ver en pantalla. La exportación incluye siempre todas.
        </p>
        <div className="mt-2 grid gap-x-6 sm:grid-cols-2 lg:grid-cols-3">
          {reporte.columnas.map((c) => (
            <label
              key={c.key}
              className="flex min-h-11 cursor-pointer items-center gap-3 text-sm text-ink"
            >
              <input
                type="checkbox"
                className="size-4 accent-brand-800"
                checked={elegidas.includes(c.key)}
                onChange={() => {
                  toggle(c.key)
                }}
              />
              {c.label}
            </label>
          ))}
        </div>
      </fieldset>
    </div>
  )
}

function Tabla({
  columnas,
  items,
  totales,
  total,
}: {
  columnas: Columna[]
  items: Record<string, string | number | null>[]
  totales: Record<string, string | number | null>
  total: number
}) {
  const hayTotales = columnas.some((c) => c.total)
  return (
    <>
      <div className="hidden max-h-[38rem] overflow-auto sm:block">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-surface-sunken text-xs font-semibold text-ink-muted shadow-[inset_0_-1px_0_var(--color-line)]">
            <tr>
              {columnas.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className={`px-4 py-2.5 whitespace-nowrap first:pl-6 last:pr-6 ${alineadaDerecha(c) ? 'text-right' : 'text-left'}`}
                >
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((fila, i) => (
              <tr key={i} className="hover:bg-brand-50/60">
                {columnas.map((c) => (
                  <td
                    key={c.key}
                    className={`max-w-[22rem] px-4 py-2.5 align-top text-ink tabular-nums first:pl-6 last:pr-6 ${alineadaDerecha(c) ? 'text-right whitespace-nowrap' : 'break-words'}`}
                  >
                    {formatCelda(c, fila[c.key] ?? null)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot className="sticky bottom-0 bg-surface-sunken font-semibold text-ink shadow-[inset_0_1px_0_var(--color-line-strong)]">
            <tr>
              {columnas.map((c, i) => (
                <td
                  key={c.key}
                  className={`px-4 py-3 whitespace-nowrap tabular-nums first:pl-6 last:pr-6 ${alineadaDerecha(c) ? 'text-right' : 'text-left'}`}
                >
                  {c.total
                    ? formatCelda(c, totales[c.key] ?? null)
                    : i === 0
                      ? `Total · ${String(total)} ${total === 1 ? 'fila' : 'filas'}`
                      : ''}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
      <ul className="divide-y divide-line sm:hidden">
        {items.map((fila, i) => (
          <li key={i} className="px-5 py-3">
            <dl className="grid gap-1">
              {columnas.map((c) => (
                <div key={c.key} className="flex items-baseline justify-between gap-4 text-sm">
                  <dt className="shrink-0 text-ink-muted">{c.label}</dt>
                  <dd className="min-w-0 text-right break-words text-ink tabular-nums">
                    {formatCelda(c, fila[c.key] ?? null)}
                  </dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
        <li className="bg-surface-sunken px-5 py-3">
          <p className="text-sm font-semibold text-ink">
            Total · {total} {total === 1 ? 'fila' : 'filas'}
          </p>
          {hayTotales && (
            <dl className="mt-1 grid gap-1">
              {columnas
                .filter((c) => c.total)
                .map((c) => (
                  <div key={c.key} className="flex items-baseline justify-between gap-4 text-sm">
                    <dt className="text-ink-muted">{c.label}</dt>
                    <dd className="font-semibold text-ink tabular-nums">
                      {formatCelda(c, totales[c.key] ?? null)}
                    </dd>
                  </div>
                ))}
            </dl>
          )}
        </li>
      </ul>
    </>
  )
}

function Contenido({ reporte }: { reporte: Reporte }) {
  const [filtros, setFiltros] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [elegidas, setElegidas] = useState(() => columnasIniciales(reporte))
  const aplicados = useDeferredValue(
    Object.fromEntries(Object.entries(filtros).filter(([, v]) => v.trim() !== '')),
  )
  const query = useQuery({
    queryKey: ['reportes', reporte.codigo, aplicados, page],
    queryFn: () => fetchPagina(reporte.codigo, aplicados, page, PAGE_SIZE),
    placeholderData: keepPreviousData,
    retry: false,
  })
  const [errorExport, setErrorExport] = useState<string | null>(null)
  const descarga = useMutation({
    mutationFn: (formato: 'xlsx' | 'csv') => exportar(reporte.codigo, aplicados, formato),
    onMutate: () => {
      setErrorExport(null)
    },
    onError: (e) => {
      setErrorExport(toProblem(e).detail)
    },
  })
  const columnas = reporte.columnas.filter((c) => elegidas.includes(c.key))
  const hayFiltros = Object.keys(aplicados).length > 0
  const sinFilas = query.data?.total === 0

  const elegir = (keys: string[]) => {
    setElegidas(keys)
    try {
      localStorage.setItem(claveColumnas(reporte.codigo), JSON.stringify(keys))
    } catch {
      // Si no se puede guardar, la elección dura lo que la página.
    }
  }

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-brand-900 sm:text-[1.75rem]">
          {reporte.titulo}
        </h1>
        <p className="mt-2 max-w-[65ch] text-ink-muted">{reporte.descripcion}</p>
      </div>
      <Panel
        title="Resultados"
        description={
          query.data
            ? `${String(query.data.total)} ${query.data.total === 1 ? 'fila' : 'filas'}${hayFiltros ? ' con los filtros aplicados' : ''}. Los totales suman todas, no solo esta página.`
            : undefined
        }
        actions={
          <>
            <Button
              icon={FileSpreadsheet}
              busy={descarga.isPending && descarga.variables === 'xlsx'}
              busyLabel="Generando…"
              disabled={descarga.isPending || sinFilas}
              onClick={() => {
                descarga.mutate('xlsx')
              }}
            >
              Excel
            </Button>
            <Button
              icon={FileText}
              busy={descarga.isPending && descarga.variables === 'csv'}
              busyLabel="Generando…"
              disabled={descarga.isPending || sinFilas}
              onClick={() => {
                descarga.mutate('csv')
              }}
            >
              CSV
            </Button>
          </>
        }
        footer={
          <span className="flex items-center gap-1.5">
            {reporte.sensible && (
              <ShieldAlert aria-hidden="true" className="size-4 shrink-0" strokeWidth={2.25} />
            )}
            {reporte.sensible ? 'Contiene datos personales o de seguridad. ' : ''}
            Cada exportación queda registrada en la auditoría con los filtros aplicados.
          </span>
        }
      >
        {reporte.filtros.length > 0 && (
          <div className="border-b border-line px-5 py-4 sm:px-6">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {reporte.filtros.map((f) => (
                <FiltroControl
                  key={f.key}
                  filtro={f}
                  value={filtros[f.key] ?? ''}
                  onChange={(v) => {
                    setFiltros((prev) => ({ ...prev, [f.key]: v }))
                    setPage(1)
                  }}
                />
              ))}
            </div>
            {hayFiltros && (
              <Button
                variant="ghost"
                icon={X}
                className="mt-3 -ml-4"
                onClick={() => {
                  setFiltros({})
                  setPage(1)
                }}
              >
                Quitar filtros
              </Button>
            )}
          </div>
        )}
        <SelectorColumnas reporte={reporte} elegidas={elegidas} onChange={elegir} />
        {(query.isError || errorExport) && (
          <div className="px-5 py-4 sm:px-6">
            <Alert tone="danger">
              {query.isError ? toProblem(query.error).detail : errorExport}
            </Alert>
          </div>
        )}
        <div
          aria-busy={query.isFetching}
          aria-live="polite"
          className={`transition-opacity duration-150 ${query.isPlaceholderData ? 'opacity-60' : ''}`}
        >
          {query.isPending && (
            <div className="grid gap-2 px-5 py-4 sm:px-6">
              {Array.from({ length: 6 }, (_, i) => (
                <span key={i} className="block h-8 animate-pulse rounded-control bg-brand-50" />
              ))}
            </div>
          )}
          {sinFilas && (
            <p className="px-5 py-10 text-center text-ink-muted sm:px-6">
              {hayFiltros ? 'Ninguna fila coincide con los filtros.' : 'Todavía no hay datos.'}
            </p>
          )}
          {query.data && query.data.total > 0 && (
            <Tabla
              columnas={columnas}
              items={query.data.items}
              totales={query.data.totales}
              total={query.data.total}
            />
          )}
        </div>
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={query.data?.total ?? 0}
          onPage={setPage}
        />
      </Panel>
    </div>
  )
}

export function ReportePage() {
  const { codigo = '' } = useParams()
  const catalogo = useQuery({ queryKey: ['reportes'], queryFn: fetchReportes, staleTime: 60_000 })
  const reporte = catalogo.data?.find((r) => r.codigo === codigo.toUpperCase())

  return (
    <>
      <Link
        to="/reportes"
        className="mb-6 inline-flex min-h-11 items-center gap-2 text-sm font-medium"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Reportes
      </Link>
      {catalogo.isError && <Alert tone="danger">{toProblem(catalogo.error).detail}</Alert>}
      {catalogo.isPending && (
        <div aria-busy="true" className="grid gap-4">
          <span className="block h-9 w-72 animate-pulse rounded-control bg-brand-50" />
          <span className="block h-96 animate-pulse rounded-panel bg-brand-50" />
        </div>
      )}
      {catalogo.isSuccess && !reporte && (
        <Alert tone="warning">El reporte no existe o no tenés permiso para verlo.</Alert>
      )}
      {reporte && <Contenido key={reporte.codigo} reporte={reporte} />}
    </>
  )
}
