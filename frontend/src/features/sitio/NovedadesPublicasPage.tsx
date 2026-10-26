import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Pagination } from '../../components/ui/Pagination'
import { toProblem } from '../../lib/api'
import { fetchNovedadesPublicas } from '../cms/api'
import { fechaLarga } from '../cms/labels'

export function NovedadesPublicasPage() {
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: ['sitio', 'novedades', page],
    queryFn: () => fetchNovedadesPublicas(page),
    placeholderData: keepPreviousData,
  })

  return (
    <div className="mx-auto max-w-[65ch]">
      <h1 className="text-2xl font-semibold tracking-tight text-brand-900 sm:text-[2rem]">
        Novedades
      </h1>
      {query.isError && (
        <div className="mt-6">
          <Alert tone="danger">{toProblem(query.error).detail}</Alert>
        </div>
      )}
      <ul className="mt-8 divide-y divide-line border-y border-line" aria-busy={query.isFetching}>
        {query.data?.items.length === 0 && (
          <li className="py-8 text-ink-muted">Todavía no hay novedades publicadas.</li>
        )}
        {query.data?.items.map((n) => (
          <li key={n.slug} className="py-6">
            <p className="text-sm text-ink-muted">{fechaLarga(n.fecha_publicacion)}</p>
            <h2 className="mt-1 text-lg font-semibold">
              <Link to={`/sitio/novedades/${n.slug}`}>{n.titulo}</Link>
            </h2>
            {n.resumen && <p className="mt-1 text-ink-muted">{n.resumen}</p>}
          </li>
        ))}
      </ul>
      {query.data && query.data.total > 10 && (
        <div className="mt-6 overflow-hidden rounded-panel border border-line">
          <Pagination page={page} pageSize={10} total={query.data.total} onPage={setPage} />
        </div>
      )}
    </div>
  )
}
