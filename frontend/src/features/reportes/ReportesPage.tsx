import { useQuery } from '@tanstack/react-query'
import { ChevronRight, ShieldAlert } from 'lucide-react'
import { Link } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { fetchReportes } from './api'

export function ReportesPage() {
  const query = useQuery({ queryKey: ['reportes'], queryFn: fetchReportes, staleTime: 60_000 })

  return (
    <>
      <PageHeader
        title="Reportes"
        description="Cada reporte se consulta paginado y se exporta a Excel o CSV con los mismos filtros: los totales del archivo coinciden con los de la pantalla."
      />
      <Panel>
        {query.isError && (
          <div className="px-5 py-4 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}
        <ul className="divide-y divide-line" aria-busy={query.isPending}>
          {query.isPending &&
            Array.from({ length: 3 }, (_, i) => (
              <li key={i} className="px-5 py-4 sm:px-6">
                <span className="block h-10 w-full animate-pulse rounded-control bg-brand-50" />
              </li>
            ))}
          {query.data?.map((r) => (
            <li key={r.codigo}>
              <Link
                to={`/reportes/${r.codigo.toLowerCase()}`}
                className="group flex items-center gap-4 px-5 py-4 text-ink no-underline hover:bg-brand-50 sm:px-6"
              >
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-brand-800 group-hover:underline">
                    {r.titulo}
                  </span>
                  <span className="block text-sm text-ink-muted">{r.descripcion}</span>
                  {r.sensible && (
                    <span className="mt-1 flex items-center gap-1.5 text-sm text-warning-700">
                      <ShieldAlert aria-hidden="true" className="size-4" strokeWidth={2.25} />
                      Contiene datos personales o de seguridad
                    </span>
                  )}
                </span>
                <ChevronRight
                  aria-hidden="true"
                  className="size-5 shrink-0 text-ink-subtle group-hover:text-brand-800"
                />
              </Link>
            </li>
          ))}
        </ul>
      </Panel>
    </>
  )
}
