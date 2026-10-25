import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Pagination } from '../../components/ui/Pagination'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { formatMoney } from '../../lib/decimal'
import { formatPeriodo } from '../ddjj/labels'
import { formatDate } from '../padron/labels'
import { fetchMesa, type EstadoComprobante } from './api'
import { ESTADO_COMPROBANTE } from './labels'

const PAGE_SIZE = 20

export function ConciliacionPage() {
  const [filters, setFilters] = useState({
    page: 1,
    estado: 'PENDIENTE_REVISION' as EstadoComprobante,
  })
  const query = useQuery({
    queryKey: ['pagos', 'mesa', filters],
    queryFn: () => fetchMesa({ ...filters, pageSize: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const rows = query.data?.items ?? []
  const enRevision = filters.estado === 'PENDIENTE_REVISION'

  return (
    <>
      <PageHeader
        title="Conciliación de pagos"
        description="Comprobantes que adjuntan los escribanos. Cada uno se confirma contra el extracto bancario antes de dar la boleta por pagada."
      />
      <Panel
        title={enRevision ? 'En revisión, por orden de llegada' : 'Comprobantes revisados'}
        description={
          enRevision && query.data
            ? `${String(query.data.total)} ${query.data.total === 1 ? 'comprobante espera' : 'comprobantes esperan'} revisión.`
            : undefined
        }
      >
        <div className="grid gap-4 border-b border-line px-5 py-4 sm:grid-cols-2 sm:px-6">
          <Select
            label="Estado"
            value={filters.estado}
            onChange={(e) => {
              setFilters({ page: 1, estado: e.target.value as EstadoComprobante })
            }}
            options={(Object.keys(ESTADO_COMPROBANTE) as EstadoComprobante[]).map((e) => ({
              value: e,
              label: ESTADO_COMPROBANTE[e].label,
            }))}
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
              {enRevision
                ? 'No hay comprobantes esperando revisión.'
                : 'Ningún comprobante en este estado.'}
            </li>
          )}
          {rows.map((c) => {
            const coincide = c.diferencia === '0.00'
            const estado = ESTADO_COMPROBANTE[c.estado]
            return (
              <li key={c.id}>
                <Link
                  to={`/tesoreria/conciliacion/${c.id}`}
                  className="group flex items-center gap-4 px-5 py-4 text-ink no-underline hover:bg-brand-50 sm:px-6"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold text-brand-800 tabular-nums group-hover:underline">
                      Boleta N° {c.boleta.numero} · Registro N° {c.boleta.registro.numero_registro}{' '}
                      · {formatPeriodo(c.boleta.periodo)}
                    </span>
                    <span className="block text-sm text-ink-muted tabular-nums">
                      Transferido el {formatDate(c.fecha_transferencia)} · Op. {c.numero_operacion}{' '}
                      · Recibido {formatLocalDateTime(new Date(c.created_at))}
                    </span>
                    <span className="block text-sm tabular-nums">
                      <span className="text-ink">Declarado {formatMoney(c.importe_declarado)}</span>
                      <span className="text-ink-muted">
                        {' '}
                        · Boleta {formatMoney(c.boleta.total_a_pagar)}
                      </span>
                      {!coincide && (
                        <span className="font-semibold text-warning-700">
                          {' '}
                          · Diferencia {formatMoney(c.diferencia)}
                        </span>
                      )}
                    </span>
                  </span>
                  <StatusIndicator tone={estado.tone} label={estado.label} />
                  <ChevronRight
                    aria-hidden="true"
                    className="hidden size-5 shrink-0 text-ink-subtle group-hover:text-brand-800 sm:block"
                  />
                </Link>
              </li>
            )
          })}
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
    </>
  )
}
