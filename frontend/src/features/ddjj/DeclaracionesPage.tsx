import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { ChevronRight, FilePlus2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Pagination } from '../../components/ui/Pagination'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import { formatMoney } from '../../lib/decimal'
import { useSession } from '../auth/session'
import { formatDate, todayIso } from '../padron/labels'
import {
  abrirDeclaracion,
  fetchDeclaraciones,
  fetchRegistrosOperables,
  type EstadoDDJJ,
} from './api'
import {
  ESTADO_DDJJ,
  formatPeriodo,
  registroLabel,
  ultimosPeriodos as ultimosPeriodosDesde,
} from './labels'

const PAGE_SIZE = 20

function ultimosPeriodos(): string[] {
  return ultimosPeriodosDesde(todayIso())
}

function puedeCargarDDJJ(can: (permission: string) => boolean): boolean {
  return can('ddjj:create_own') || can('ddjj:approve')
}

function NuevaDeclaracionDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const periodos = ultimosPeriodos()
  const registros = useQuery({
    queryKey: ['ddjj', 'registros'],
    queryFn: fetchRegistrosOperables,
    enabled: open,
  })
  const [registroId, setRegistroId] = useState('')
  const [periodo, setPeriodo] = useState(periodos[1] ?? '')
  const elegido = registroId || registros.data?.[0]?.id || ''
  const abrir = useMutation({
    mutationFn: () => abrirDeclaracion({ registro_id: elegido, periodo }),
    onSuccess: (ddjj) => {
      void navigate(`/ddjj/${ddjj.id}`)
    },
  })
  const problem = abrir.isError ? toProblem(abrir.error) : null
  const sinRegistros = registros.isSuccess && registros.data.length === 0

  return (
    <Dialog
      open={open}
      onClose={() => {
        abrir.reset()
        onClose()
      }}
      title="Nueva declaración jurada"
      description="Si el registro ya tiene una DDJJ en curso para ese período, se abre esa."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={FilePlus2}
            busy={abrir.isPending}
            busyLabel="Abriendo…"
            disabled={!elegido || !periodo}
            onClick={() => {
              abrir.mutate()
            }}
          >
            Abrir declaración
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {problem && <Alert tone="danger">{problem.detail}</Alert>}
        {sinRegistros && (
          <Alert tone="warning">
            No tenés un cargo vigente en ningún registro notarial. Si es un error, comunicate con la
            Caja.
          </Alert>
        )}
        {registros.isError && <Alert tone="danger">{toProblem(registros.error).detail}</Alert>}
        <Select
          label="Registro notarial"
          value={elegido}
          disabled={!registros.data?.length}
          onChange={(e) => {
            setRegistroId(e.target.value)
          }}
          options={(registros.data ?? []).map((r) => ({ value: r.id, label: registroLabel(r) }))}
        />
        <Select
          label="Período"
          value={periodo}
          onChange={(e) => {
            setPeriodo(e.target.value)
          }}
          options={periodos.map((p, i) => ({
            value: p,
            label: i === 0 ? `${formatPeriodo(p)} (en curso)` : formatPeriodo(p),
          }))}
        />
        <p className="text-sm text-ink-muted">
          Se declaran los actos autorizados en el mes. La DDJJ se presenta una vez terminado el
          período.
        </p>
      </div>
    </Dialog>
  )
}

export function DeclaracionesPage() {
  const { can } = useSession()
  const puedeCargar = puedeCargarDDJJ(can)
  const periodos = ultimosPeriodos()
  const [filters, setFilters] = useState({ page: 1, periodo: '', estado: '' as EstadoDDJJ | '' })
  const query = useQuery({
    queryKey: ['ddjj', 'declaraciones', filters],
    queryFn: () => fetchDeclaraciones({ ...filters, pageSize: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const [creating, setCreating] = useState(false)
  const rows = query.data?.items ?? []

  return (
    <>
      <PageHeader
        title="Declaraciones juradas"
        description="Actos autorizados en cada registro, mes por mes. Al presentar la declaración, la Caja liquida los aportes y emite la boleta."
      />
      <Panel
        title="Declaraciones"
        actions={
          puedeCargar ? (
            <Button
              variant="primary"
              icon={FilePlus2}
              onClick={() => {
                setCreating(true)
              }}
            >
              Nueva declaración
            </Button>
          ) : undefined
        }
      >
        <div className="grid gap-4 border-b border-line px-5 py-4 sm:grid-cols-2 sm:px-6">
          <Select
            label="Período"
            value={filters.periodo}
            onChange={(e) => {
              setFilters((f) => ({ ...f, periodo: e.target.value, page: 1 }))
            }}
            options={[
              { value: '', label: 'Todos' },
              ...periodos.map((p) => ({ value: p, label: formatPeriodo(p) })),
            ]}
          />
          <Select
            label="Estado"
            value={filters.estado}
            onChange={(e) => {
              setFilters((f) => ({ ...f, estado: e.target.value as EstadoDDJJ | '', page: 1 }))
            }}
            options={[
              { value: '', label: 'Todos' },
              ...Object.entries(ESTADO_DDJJ).map(([value, { label }]) => ({ value, label })),
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
              {filters.periodo || filters.estado
                ? 'Ninguna declaración coincide con los filtros.'
                : puedeCargar
                  ? 'Todavía no hay declaraciones. Abrí la del último mes con «Nueva declaración».'
                  : 'Todavía no hay declaraciones juradas.'}
            </li>
          )}
          {rows.map((d) => (
            <li key={d.id}>
              <Link
                to={`/ddjj/${d.id}`}
                className="group flex items-center gap-4 px-5 py-4 text-ink no-underline hover:bg-brand-50 sm:px-6"
              >
                <span className="w-24 shrink-0 text-xl font-semibold text-brand-900 tabular-nums">
                  {formatPeriodo(d.periodo)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-brand-800 group-hover:underline">
                    {registroLabel(d.registro)}
                    {d.numero_rectificativa > 0 &&
                      ` · Rectificativa ${String(d.numero_rectificativa)}`}
                  </span>
                  <span className="block text-sm text-ink-muted tabular-nums">
                    {d.cantidad_actos} {d.cantidad_actos === 1 ? 'acto' : 'actos'}
                    {d.total_protocolos !== null &&
                      ` · Protocolos ${formatMoney(d.total_protocolos)}`}
                    {d.vencimiento && ` · Vence ${formatDate(d.vencimiento)}`}
                  </span>
                </span>
                <StatusIndicator
                  tone={ESTADO_DDJJ[d.estado].tone}
                  label={ESTADO_DDJJ[d.estado].label}
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
      <NuevaDeclaracionDialog
        key={`nueva-${String(creating)}`}
        open={creating}
        onClose={() => {
          setCreating(false)
        }}
      />
    </>
  )
}
