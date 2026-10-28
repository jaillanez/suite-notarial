import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'
import { Link } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Pagination } from '../../components/ui/Pagination'
import { toProblem } from '../../lib/api'
import { fetchNovedadesPublicas, type SeccionNovedad } from '../cms/api'
import { SECCION_NOVEDAD, fechaLarga } from '../cms/labels'

const PAGINA = 12

function filtro(activo: boolean): string {
  return `inline-flex min-h-11 items-center rounded-control px-3 text-sm font-medium no-underline transition-colors duration-150 ease-out-quint ${
    activo ? 'bg-brand-800 text-white' : 'text-ink hover:bg-brand-50 hover:text-brand-800'
  }`
}

export function NovedadesPublicasPage() {
  const [params, setParams] = useSearchParams()
  const valor = params.get('seccion')
  const seccion = valor && valor in SECCION_NOVEDAD ? (valor as SeccionNovedad) : null
  const page = Math.max(1, Number(params.get('pagina')) || 1)
  const query = useQuery({
    queryKey: ['sitio', 'novedades', seccion, page],
    queryFn: () => fetchNovedadesPublicas(page, seccion),
    placeholderData: keepPreviousData,
  })

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="text-2xl font-semibold tracking-tight text-brand-900 sm:text-[2rem]">
        {seccion ? SECCION_NOVEDAD[seccion] : 'Novedades'}
      </h1>
      <nav aria-label="Secciones" className="mt-5 -ml-3 flex flex-wrap gap-1">
        <Link
          to="/sitio/novedades"
          className={filtro(seccion === null)}
          aria-current={seccion === null ? 'page' : undefined}
        >
          Todas
        </Link>
        {(Object.keys(SECCION_NOVEDAD) as SeccionNovedad[]).map((s) => (
          <Link
            key={s}
            to={`/sitio/novedades?seccion=${s}`}
            className={filtro(seccion === s)}
            aria-current={seccion === s ? 'page' : undefined}
          >
            {SECCION_NOVEDAD[s]}
          </Link>
        ))}
      </nav>
      {query.isError && (
        <div className="mt-6">
          <Alert tone="danger">{toProblem(query.error).detail}</Alert>
        </div>
      )}
      <ul className="mt-6 divide-y divide-line border-y border-line" aria-busy={query.isFetching}>
        {query.data?.items.length === 0 && (
          <li className="py-8 text-ink-muted">
            {seccion
              ? 'Todavía no hay notas publicadas en esta sección.'
              : 'Todavía no hay novedades publicadas.'}
          </li>
        )}
        {query.data?.items.map((n) => (
          <li key={n.slug} className="grid gap-4 py-6 sm:grid-cols-[1fr_12rem] sm:items-start">
            <div>
              <p className="text-sm text-ink-muted">
                <span className="font-medium text-brand-800">{n.seccion_texto}</span>
                <span aria-hidden="true"> · </span>
                <time dateTime={n.fecha_publicacion} className="tabular-nums">
                  {fechaLarga(n.fecha_publicacion)}
                </time>
              </p>
              <h2 className="mt-1 text-lg font-semibold text-balance">
                <Link to={`/sitio/novedades/${n.slug}`}>{n.titulo}</Link>
              </h2>
              {n.resumen && <p className="mt-1 max-w-[65ch] text-ink-muted">{n.resumen}</p>}
            </div>
            {n.imagen_url && (
              <img
                src={n.imagen_url}
                alt=""
                loading="lazy"
                className="row-start-1 aspect-[3/2] w-full rounded-panel object-cover sm:col-start-2"
              />
            )}
          </li>
        ))}
      </ul>
      {query.data && query.data.total > PAGINA && (
        <div className="mt-6 overflow-hidden rounded-panel border border-line">
          <Pagination
            page={page}
            pageSize={PAGINA}
            total={query.data.total}
            onPage={(p) => {
              const nuevos = new URLSearchParams(params)
              nuevos.set('pagina', String(p))
              setParams(nuevos)
            }}
          />
        </div>
      )}
    </div>
  )
}
