import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { toProblem } from '../../lib/api'
import { fetchNovedadPublica } from '../cms/api'
import { fechaLarga, parrafos } from '../cms/labels'

export function NovedadPublicaPage() {
  const { slug = '' } = useParams()
  const query = useQuery({
    queryKey: ['sitio', 'novedad', slug],
    queryFn: () => fetchNovedadPublica(slug),
    retry: false,
  })
  const n = query.data

  return (
    <article className="mx-auto max-w-[65ch]">
      <Link
        to="/sitio/novedades"
        className="inline-flex min-h-11 items-center gap-2 text-sm font-medium"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Novedades
      </Link>
      {query.isError && (
        <div className="mt-6">
          <Alert tone="warning">
            {toProblem(query.error).status === 404
              ? 'Esta novedad no existe o ya no está publicada.'
              : toProblem(query.error).detail}
          </Alert>
        </div>
      )}
      {query.isPending && (
        <div aria-busy="true" className="mt-6 grid gap-3">
          <span className="block h-10 w-3/4 animate-pulse rounded-control bg-brand-50" />
          <span className="block h-40 animate-pulse rounded-control bg-brand-50" />
        </div>
      )}
      {n && (
        <>
          <p className="mt-6 text-sm text-ink-muted">{fechaLarga(n.fecha_publicacion)}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-balance text-brand-900 sm:text-[2rem]">
            {n.titulo}
          </h1>
          {n.resumen && <p className="mt-3 text-lg text-ink-muted">{n.resumen}</p>}
          <div className="mt-8 grid gap-4 text-lg leading-relaxed text-ink">
            {/* Texto plano: React lo escapa; nunca se interpreta como HTML. */}
            {parrafos(n.contenido).map((p, i) => (
              <p key={i} className="whitespace-pre-line">
                {p}
              </p>
            ))}
          </div>
        </>
      )}
    </article>
  )
}
