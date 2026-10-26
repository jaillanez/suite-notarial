import { useQuery } from '@tanstack/react-query'
import { ArrowRight, ChevronRight, FileDown } from 'lucide-react'
import { Link } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { toProblem } from '../../lib/api'
import { formatDate } from '../padron/labels'
import { formatTamano } from '../pagos/labels'
import { fetchSitio, type Autoridad, type DocumentoPublico } from '../cms/api'
import { fechaLarga, fechaLocal, rutaLocal } from '../cms/labels'

function Seccion({
  id,
  titulo,
  children,
  accion,
}: {
  id: string
  titulo: string
  children: React.ReactNode
  accion?: React.ReactNode
}) {
  return (
    <section aria-labelledby={id} className="border-t border-line pt-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id={id} className="text-xl font-semibold text-brand-900">
          {titulo}
        </h2>
        {accion}
      </div>
      <div className="mt-6">{children}</div>
    </section>
  )
}

function mandato(a: Autoridad): string | null {
  if (!a.mandato_desde && !a.mandato_hasta) return null
  if (a.mandato_desde && a.mandato_hasta) {
    return `Mandato ${formatDate(a.mandato_desde)} – ${formatDate(a.mandato_hasta)}`
  }
  return a.mandato_desde
    ? `Desde ${formatDate(a.mandato_desde)}`
    : `Hasta ${formatDate(a.mandato_hasta)}`
}

function DocumentoItem({ doc }: { doc: DocumentoPublico }) {
  return (
    <li className="grid gap-3 py-5 sm:grid-cols-[5rem_1fr_auto] sm:items-start sm:gap-6">
      <span className="text-2xl font-semibold text-brand-900 tabular-nums">{doc.ejercicio}</span>
      <div className="min-w-0">
        <h4 className="font-semibold text-ink">{doc.titulo}</h4>
        {doc.descripcion && <p className="mt-1 max-w-[65ch] text-ink-muted">{doc.descripcion}</p>}
        <p className="mt-1 text-sm text-ink-muted tabular-nums">
          {doc.paginas} {doc.paginas === 1 ? 'página' : 'páginas'} ·{' '}
          {formatTamano(doc.tamano_bytes)}
          {' · '}
          {doc.versiones_anteriores.length > 0
            ? `Actualizado el ${fechaLocal(doc.actualizado)} (versión ${String(doc.version)})`
            : `Publicado el ${fechaLocal(doc.fecha_publicacion)}`}
        </p>
        {doc.motivo_actualizacion && (
          <p className="mt-1 text-sm text-ink-muted">Motivo: {doc.motivo_actualizacion}</p>
        )}
        <details className="group mt-2 text-sm">
          <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-1.5 font-medium text-action-700 [&::-webkit-details-marker]:hidden">
            <ChevronRight
              aria-hidden="true"
              className="size-4 transition-transform duration-150 group-open:rotate-90"
              strokeWidth={2.25}
            />
            Huella y versiones anteriores
          </summary>
          <div className="mt-1 grid gap-2 rounded-control bg-surface-sunken p-3">
            <p className="text-ink-muted">
              Huella SHA-256 de la versión vigente:{' '}
              <code className="font-mono text-xs break-all text-ink">{doc.sha256}</code>
            </p>
            {doc.versiones_anteriores.length > 0 ? (
              <ul className="grid gap-1">
                {doc.versiones_anteriores.map((v) => (
                  <li key={v.version} className="tabular-nums">
                    <a href={rutaLocal(v.url)}>Versión {v.version}</a>
                    <span className="text-ink-muted"> · {fechaLocal(v.created_at)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-ink-muted">Sin versiones anteriores.</p>
            )}
          </div>
        </details>
      </div>
      <a
        href={rutaLocal(doc.url)}
        className="inline-flex min-h-11 items-center gap-2 justify-self-start rounded-control border border-line-strong bg-surface px-4 text-sm font-semibold text-brand-800 no-underline transition-colors duration-150 ease-out-quint hover:border-brand-700 hover:bg-brand-50"
      >
        <FileDown aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Descargar PDF
      </a>
    </li>
  )
}

export function SitioPage() {
  const query = useQuery({ queryKey: ['sitio'], queryFn: fetchSitio })
  const sitio = query.data
  const grupos = new Map<string, DocumentoPublico[]>()
  for (const doc of sitio?.documentos ?? []) {
    grupos.set(doc.tipo_texto, [...(grupos.get(doc.tipo_texto) ?? []), doc])
  }

  return (
    <div className="grid gap-10">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-brand-900 sm:text-[2rem]">
          Caja Notarial de San Juan
        </h1>
        <p className="mt-3 max-w-[60ch] text-lg text-ink-muted">
          Información institucional, autoridades y documentos oficiales: estados contables, memorias
          y resoluciones, publicados con su huella de integridad.
        </p>
      </div>
      {query.isError && <Alert tone="danger">{toProblem(query.error).detail}</Alert>}
      {query.isPending && (
        <div aria-busy="true" className="grid gap-4">
          {Array.from({ length: 3 }, (_, i) => (
            <span key={i} className="block h-28 animate-pulse rounded-panel bg-brand-50" />
          ))}
        </div>
      )}
      {sitio && (
        <>
          <Seccion
            id="novedades"
            titulo="Novedades"
            accion={
              sitio.novedades.length > 0 ? (
                <Link
                  to="/sitio/novedades"
                  className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium"
                >
                  Todas las novedades
                  <ArrowRight aria-hidden="true" className="size-4" strokeWidth={2.25} />
                </Link>
              ) : undefined
            }
          >
            {sitio.novedades.length === 0 ? (
              <p className="text-ink-muted">Todavía no hay novedades publicadas.</p>
            ) : (
              <ul className="grid gap-6 sm:grid-cols-3">
                {sitio.novedades.map((n) => (
                  <li key={n.slug}>
                    <p className="text-sm text-ink-muted">{fechaLarga(n.fecha_publicacion)}</p>
                    <h3 className="mt-1 text-lg font-semibold">
                      <Link to={`/sitio/novedades/${n.slug}`}>{n.titulo}</Link>
                    </h3>
                    {n.resumen && <p className="mt-1 text-ink-muted">{n.resumen}</p>}
                  </li>
                ))}
              </ul>
            )}
          </Seccion>

          <Seccion id="autoridades" titulo="Autoridades">
            {sitio.autoridades.length === 0 ? (
              <p className="text-ink-muted">La nómina de autoridades se publicará próximamente.</p>
            ) : (
              <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
                {sitio.autoridades.map((a) => (
                  <div key={a.id}>
                    <dt className="text-sm font-medium text-ink-muted">{a.cargo}</dt>
                    <dd className="mt-0.5 font-semibold text-ink">{a.nombre}</dd>
                    {mandato(a) && (
                      <dd className="text-sm text-ink-muted tabular-nums">{mandato(a)}</dd>
                    )}
                  </div>
                ))}
              </dl>
            )}
          </Seccion>

          <Seccion id="documentos" titulo="Documentos oficiales">
            {grupos.size === 0 ? (
              <p className="text-ink-muted">Todavía no hay documentos publicados.</p>
            ) : (
              <div className="grid gap-8">
                {[...grupos.entries()].map(([tipo, docs]) => (
                  <div key={tipo}>
                    <h3 className="text-sm font-semibold text-ink-muted">{tipo}</h3>
                    <ul className="mt-2 divide-y divide-line border-y border-line">
                      {docs.map((d) => (
                        <DocumentoItem key={d.slug} doc={d} />
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </Seccion>
        </>
      )}
    </div>
  )
}
