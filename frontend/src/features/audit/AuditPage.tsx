import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { StatusIndicator, type Tone } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Pagination } from '../../components/ui/Pagination'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { EVENT_LABELS, fetchAuditLogs, type AuditEntry } from './api'

const PAGE_SIZE = 25

const SEVERITY: Record<AuditEntry['severity'], { tone: Tone; label: string }> = {
  INFO: { tone: 'unknown', label: 'Informativo' },
  WARNING: { tone: 'warning', label: 'Atención' },
  CRITICAL: { tone: 'danger', label: 'Crítico' },
}

function Changes({ entry }: { entry: AuditEntry }) {
  const blocks: [string, Record<string, unknown> | null][] = [
    ['Antes', entry.old_value],
    ['Después', entry.new_value],
    ['Detalle', entry.details],
  ]
  const present = blocks.filter(([, value]) => value && Object.keys(value).length > 0)
  if (present.length === 0) return <span className="text-ink-subtle">—</span>
  return (
    <details className="group">
      <summary className="inline-flex min-h-11 cursor-pointer items-center text-sm font-semibold text-action-700 underline underline-offset-4">
        Ver datos
      </summary>
      <dl className="mt-2 space-y-2">
        {present.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs font-semibold text-ink-muted">{label}</dt>
            <dd>
              <pre className="mt-1 max-w-[28rem] overflow-x-auto rounded-control bg-surface-sunken px-3 py-2 font-mono text-xs whitespace-pre-wrap text-ink">
                {JSON.stringify(value, null, 2)}
              </pre>
            </dd>
          </div>
        ))}
      </dl>
    </details>
  )
}

export function AuditPage() {
  const [page, setPage] = useState(1)
  const [eventType, setEventType] = useState('')
  const query = useQuery({
    queryKey: ['audit', { page, eventType }],
    queryFn: () => fetchAuditLogs({ page, pageSize: PAGE_SIZE, eventType }),
    placeholderData: keepPreviousData,
  })
  const rows = query.data?.items ?? []

  return (
    <>
      <PageHeader
        title="Auditoría de seguridad"
        description="Registro inmutable: ninguna fila se puede modificar ni borrar, ni siquiera desde la base de datos con el usuario de la aplicación."
      />
      <Panel title="Eventos">
        <div className="border-b border-line px-5 py-4 sm:px-6">
          <Select
            label="Tipo de evento"
            value={eventType}
            onChange={(e) => {
              setEventType(e.target.value)
              setPage(1)
            }}
            options={[
              { value: '', label: 'Todos' },
              ...Object.entries(EVENT_LABELS).map(([value, label]) => ({ value, label })),
            ]}
            className="max-w-sm"
          />
        </div>
        {query.isError && (
          <div className="px-5 py-4 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}
        <div className="max-h-[40rem] overflow-auto" aria-busy={query.isFetching}>
          <table className="w-full min-w-[52rem] border-collapse text-left text-sm">
            <caption className="sr-only">Eventos de auditoría de seguridad</caption>
            <thead className="sticky top-0 z-10 bg-surface-sunken text-xs font-semibold text-ink-muted">
              <tr className="border-b border-line">
                <th scope="col" className="px-5 py-3 sm:px-6">
                  Fecha (San Juan)
                </th>
                <th scope="col" className="px-3 py-3">
                  Evento
                </th>
                <th scope="col" className="px-3 py-3">
                  Quién / sobre quién
                </th>
                <th scope="col" className="px-3 py-3">
                  IP
                </th>
                <th scope="col" className="px-5 py-3 sm:px-6">
                  Datos
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
                    No hay eventos de este tipo.
                  </td>
                </tr>
              )}
              {rows.map((entry) => {
                const severity = SEVERITY[entry.severity]
                return (
                  <tr key={entry.id} className="align-top">
                    <td className="px-5 py-3 whitespace-nowrap text-ink tabular-nums sm:px-6">
                      {formatLocalDateTime(new Date(entry.event_timestamp))}
                    </td>
                    <td className="px-3 py-3">
                      <span className="block font-semibold text-ink">
                        {EVENT_LABELS[entry.event_type] ?? entry.event_type}
                      </span>
                      {entry.severity !== 'INFO' && (
                        <span className="mt-1 block">
                          <StatusIndicator tone={severity.tone} label={severity.label} />
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-ink">
                      <span className="block">{entry.actor_email ?? 'Sin sesión'}</span>
                      {entry.target_email && entry.target_email !== entry.actor_email && (
                        <span className="block text-ink-muted">→ {entry.target_email}</span>
                      )}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap text-ink-muted tabular-nums">
                      {entry.ip_address ?? '—'}
                    </td>
                    <td className="px-5 py-1 sm:px-6">
                      <Changes entry={entry} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={query.data?.total ?? 0}
          onPage={setPage}
        />
      </Panel>
    </>
  )
}
