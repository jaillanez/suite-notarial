import { useQuery } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { fetchCorridas, type Corrida } from './api'
import { AREA, ESTADO, MODO } from './labels'

export function Cuadra({ corrida }: { corrida: Pick<Corrida, 'cuadra' | 'estado'> }) {
  if (corrida.cuadra === null) return <StatusIndicator tone="unknown" label="Sin cuadratura" />
  return corrida.cuadra ? (
    <StatusIndicator tone="success" label="Cuadra" />
  ) : (
    <StatusIndicator tone="danger" label="No cuadra" />
  )
}

function Fila({ corrida }: { corrida: Corrida }) {
  const firmadas = new Set(corrida.conformidades.map((c) => c.area))
  return (
    <li>
      <Link
        to={`/migracion/${corrida.id}`}
        className="group flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-4 text-ink no-underline hover:bg-brand-50 sm:flex-nowrap sm:px-6"
      >
        <span className="min-w-0 flex-1">
          <span className="block font-semibold text-brand-800 group-hover:underline">
            {MODO[corrida.modo]}
            {corrida.homologacion_ejemplo && (
              <span className="font-normal text-ink-muted"> · homologación de ejemplo</span>
            )}
          </span>
          <span className="block text-sm text-ink-muted tabular-nums">
            {formatLocalDateTime(new Date(corrida.created_at))} · {corrida.operador}
          </span>
          {corrida.bloqueantes !== null && (
            <span className="block text-sm text-ink-muted tabular-nums">
              {corrida.bloqueantes} bloqueantes · {corrida.advertencias ?? 0} advertencias
              {corrida.modo === 'SIMULACRO' &&
                ` · Conformidad: ${(['TESORERIA', 'CAJA'] as const)
                  .map((a) => `${AREA[a]} ${firmadas.has(a) ? 'firmó' : 'pendiente'}`)
                  .join(', ')}`}
            </span>
          )}
        </span>
        <span className="flex shrink-0 flex-wrap gap-2">
          <Cuadra corrida={corrida} />
          <StatusIndicator
            tone={ESTADO[corrida.estado].tone}
            label={ESTADO[corrida.estado].label}
          />
        </span>
        <ChevronRight
          aria-hidden="true"
          className="hidden size-5 shrink-0 text-ink-subtle group-hover:text-brand-800 sm:block"
        />
      </Link>
    </li>
  )
}

export function CorridasPage() {
  const corridas = useQuery({ queryKey: ['migracion', 'corridas'], queryFn: fetchCorridas })
  const filas = corridas.data ?? []

  return (
    <>
      <PageHeader
        title="Migración del sistema anterior"
        description="Simulacros y carga definitiva del padrón y del histórico de boletas y pagos. Cada corrida cuadra al centavo contra los totales que declara el sistema anterior; ninguna diferencia se compensa."
      />
      <Panel title="Corridas">
        {corridas.isError && (
          <div className="px-5 py-4 sm:px-6">
            <Alert tone="danger">{toProblem(corridas.error).detail}</Alert>
          </div>
        )}
        <ul className="divide-y divide-line" aria-busy={corridas.isFetching}>
          {corridas.isPending &&
            Array.from({ length: 3 }, (_, i) => (
              <li key={i} className="px-5 py-4 sm:px-6">
                <span className="block h-12 w-full animate-pulse rounded-control bg-brand-50" />
              </li>
            ))}
          {corridas.isSuccess && filas.length === 0 && (
            <li className="px-5 py-10 sm:px-6">
              <p className="mx-auto max-w-[65ch] text-center text-ink-muted">
                Todavía no hay corridas. Los simulacros y la carga definitiva se ejecutan por
                consola con el lote de extracción del sistema anterior; acá se revisan la cuadratura
                y las observaciones, y Tesorería y Caja dan su conformidad.
              </p>
            </li>
          )}
          {filas.map((c) => (
            <Fila key={c.id} corrida={c} />
          ))}
        </ul>
      </Panel>
    </>
  )
}
