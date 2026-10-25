import { RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'

import { StatusIndicator, type Tone } from '../../components/StatusIndicator'
import { formatLocalDateTime, formatLocalTime, formatUtcTime } from '../../lib/datetime'
import type { Health } from './api'
import { HEALTH_REFRESH_MS, useHealth } from './useHealth'

interface Summary {
  tone: Tone
  title: string
  detail: string
}

type View = { kind: 'loading' } | { kind: 'unreachable' } | { kind: 'ready'; health: Health }

function summarize(view: View): Summary {
  switch (view.kind) {
    case 'loading':
      return { tone: 'unknown', title: 'Verificando servicios…', detail: '' }
    case 'unreachable':
      return {
        tone: 'danger',
        title: 'No se pudo contactar la API',
        detail:
          'El servidor de la Suite no respondió. Verificá que el servicio esté en ejecución y volvé a intentar.',
      }
    case 'ready':
      return view.health.db === 'up'
        ? {
            tone: 'success',
            title: 'Todos los servicios operativos',
            detail: 'La API responde y la base de datos acepta consultas.',
          }
        : {
            tone: 'warning',
            title: 'Servicio degradado',
            detail:
              'La API responde, pero la base de datos no acepta consultas. Las operaciones que guardan o leen datos van a fallar.',
          }
  }
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-4 sm:px-6">
      <dt className="text-sm font-medium text-ink-muted">{label}</dt>
      <dd className="text-ink">{children}</dd>
    </div>
  )
}

function SkeletonLine({ className }: { className: string }) {
  return <span className={`block animate-pulse rounded-control bg-brand-50 ${className}`} />
}

export function SystemStatusPage() {
  const query = useHealth()

  const view: View = query.isError
    ? { kind: 'unreachable' }
    : query.data
      ? { kind: 'ready', health: query.data }
      : { kind: 'loading' }
  const summary = summarize(view)
  const checkedAt = query.dataUpdatedAt || query.errorUpdatedAt
  const refreshing = query.isFetching

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
      <h1 className="text-2xl font-semibold tracking-tight text-brand-900 sm:text-[1.75rem]">
        Estado del sistema
      </h1>
      <p className="mt-2 max-w-[65ch] text-ink-muted">
        Disponibilidad de los servicios de la Suite Notarial. Se verifica automáticamente cada{' '}
        {HEALTH_REFRESH_MS / 1000} segundos.
      </p>

      <section
        aria-labelledby="estado-resumen"
        className="mt-8 overflow-hidden rounded-panel border border-line bg-surface shadow-panel"
      >
        <div
          className="flex flex-col gap-4 border-b border-line px-5 py-5 sm:flex-row sm:items-start sm:justify-between sm:px-6"
          aria-live="polite"
          aria-busy={view.kind === 'loading'}
        >
          <div className="min-w-0">
            <h2 id="estado-resumen" className="text-lg font-semibold text-ink">
              {summary.title}
            </h2>
            {summary.detail && (
              <p className="mt-1 max-w-[65ch] text-sm text-ink-muted">{summary.detail}</p>
            )}
          </div>
          <button
            type="button"
            onClick={() => void query.refetch()}
            disabled={refreshing}
            className="inline-flex min-h-11 shrink-0 cursor-pointer items-center justify-center gap-2 self-start rounded-control border border-line-strong bg-surface px-4 text-sm font-semibold text-brand-800 transition-colors duration-150 ease-out-quint hover:border-brand-700 hover:bg-brand-50 active:bg-brand-100 disabled:cursor-progress disabled:opacity-60"
          >
            <RefreshCw
              aria-hidden="true"
              className={`size-4 ${refreshing ? 'animate-spin' : ''}`}
              strokeWidth={2.25}
            />
            {refreshing ? 'Verificando…' : 'Verificar ahora'}
          </button>
        </div>

        <dl className="divide-y divide-line">
          <Row label="API de la Suite">
            {view.kind === 'loading' ? (
              <SkeletonLine className="h-7 w-28" />
            ) : view.kind === 'unreachable' ? (
              <StatusIndicator tone="danger" label="Sin respuesta" />
            ) : (
              <StatusIndicator tone="success" label="Operativa" />
            )}
          </Row>
          <Row label="Base de datos">
            {view.kind === 'loading' ? (
              <SkeletonLine className="h-7 w-28" />
            ) : view.kind === 'unreachable' ? (
              <StatusIndicator tone="unknown" label="Sin datos" />
            ) : view.health.db === 'up' ? (
              <StatusIndicator tone="success" label="Operativa" />
            ) : (
              <StatusIndicator tone="warning" label="Sin conexión" />
            )}
          </Row>
          <Row label="Hora del servidor">
            {view.kind === 'loading' ? (
              <SkeletonLine className="h-5 w-56" />
            ) : view.kind === 'unreachable' ? (
              <span className="text-sm text-ink-subtle">No disponible</span>
            ) : (
              <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1 tabular-nums">
                <time dateTime={view.health.timeUtc.toISOString()} className="font-medium">
                  {formatLocalDateTime(view.health.timeUtc)}
                </time>
                <span className="text-sm text-ink-muted">
                  San Juan · {formatUtcTime(view.health.timeUtc)} UTC
                </span>
              </span>
            )}
          </Row>
        </dl>

        <p className="border-t border-line bg-surface-sunken px-5 py-3 text-xs text-ink-muted sm:px-6">
          {checkedAt ? (
            <>
              Última verificación:{' '}
              <time dateTime={new Date(checkedAt).toISOString()} className="tabular-nums">
                {formatLocalTime(new Date(checkedAt))}
              </time>
            </>
          ) : (
            'Sin verificaciones todavía.'
          )}
        </p>
      </section>
    </main>
  )
}
