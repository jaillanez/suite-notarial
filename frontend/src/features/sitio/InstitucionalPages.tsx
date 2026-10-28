import { useQuery } from '@tanstack/react-query'
import { ChevronRight, FileDown, Mail, MapPin, Phone } from 'lucide-react'
import { useParams } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { toProblem } from '../../lib/api'
import { formatDate } from '../padron/labels'
import { formatTamano } from '../pagos/labels'
import { fetchPaginaPublica, fetchSitio, type Autoridad, type DocumentoPublico } from '../cms/api'
import { fechaLarga, fechaLocal, parrafos, rutaLocal } from '../cms/labels'

function Cargando() {
  return (
    <div aria-busy="true" className="mt-6 grid gap-3">
      <span className="sr-only">Cargando…</span>
      <span className="block h-10 w-2/3 animate-pulse rounded-control bg-brand-50" />
      <span className="block h-40 animate-pulse rounded-control bg-brand-50" />
    </div>
  )
}

function Titulo({ children, detalle }: { children: React.ReactNode; detalle?: React.ReactNode }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-balance text-brand-900 sm:text-[2rem]">
        {children}
      </h1>
      {detalle && <p className="mt-3 max-w-[60ch] text-lg text-ink-muted">{detalle}</p>}
    </div>
  )
}

/** Página institucional cargada desde el gestor (Quiénes somos, Ley de creación…). */
export function PaginaPublicaPage() {
  const { slug = '' } = useParams()
  const query = useQuery({
    queryKey: ['sitio', 'pagina', slug],
    queryFn: () => fetchPaginaPublica(slug),
    retry: false,
  })
  const p = query.data
  return (
    <article className="mx-auto max-w-[65ch]">
      {query.isError && (
        <Alert tone="warning">
          {toProblem(query.error).status === 404
            ? 'Esta página no existe o todavía no está publicada.'
            : toProblem(query.error).detail}
        </Alert>
      )}
      {query.isPending && <Cargando />}
      {p && (
        <>
          <p className="text-sm font-medium text-ink-muted">{p.grupo_texto}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-balance text-brand-900 sm:text-[2rem]">
            {p.titulo}
          </h1>
          <div className="mt-8 grid gap-4 text-lg leading-relaxed text-ink">
            {/* Texto plano: React lo escapa; nunca se interpreta como HTML. */}
            {parrafos(p.contenido).map((texto, i) => (
              <p key={i} className="whitespace-pre-line">
                {texto}
              </p>
            ))}
          </div>
          <p className="mt-10 border-t border-line pt-4 text-sm text-ink-muted">
            Actualizado el {fechaLarga(p.updated_at)}.
          </p>
        </>
      )}
    </article>
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

export function AutoridadesPublicasPage() {
  const query = useQuery({ queryKey: ['sitio'], queryFn: fetchSitio })
  const autoridades = query.data?.autoridades
  return (
    <div className="mx-auto max-w-4xl">
      <Titulo detalle="Consejo de administración y sindicatura vigentes.">Autoridades</Titulo>
      {query.isError && (
        <div className="mt-6">
          <Alert tone="danger">{toProblem(query.error).detail}</Alert>
        </div>
      )}
      {query.isPending && <Cargando />}
      {autoridades?.length === 0 && (
        <p className="mt-8 text-ink-muted">La nómina de autoridades se publicará próximamente.</p>
      )}
      {autoridades && autoridades.length > 0 && (
        <dl className="mt-8 grid gap-x-10 border-t border-line sm:grid-cols-2">
          {autoridades.map((a) => (
            <div key={a.id} className="border-b border-line py-5">
              <dt className="text-sm text-ink-muted">{a.cargo}</dt>
              <dd className="mt-0.5 text-lg font-semibold text-ink">{a.nombre}</dd>
              {mandato(a) && <dd className="text-sm text-ink-muted tabular-nums">{mandato(a)}</dd>}
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

function DocumentoItem({ doc }: { doc: DocumentoPublico }) {
  return (
    <li className="grid gap-3 py-5 sm:grid-cols-[5rem_1fr_auto] sm:items-start sm:gap-6">
      <span className="text-2xl font-semibold text-brand-900 tabular-nums">{doc.ejercicio}</span>
      <div className="min-w-0">
        <h3 className="font-semibold text-ink">{doc.titulo}</h3>
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

export function DocumentosPublicosPage() {
  const query = useQuery({ queryKey: ['sitio'], queryFn: fetchSitio })
  const grupos = new Map<string, DocumentoPublico[]>()
  for (const doc of query.data?.documentos ?? []) {
    grupos.set(doc.tipo_texto, [...(grupos.get(doc.tipo_texto) ?? []), doc])
  }
  return (
    <div className="mx-auto max-w-4xl">
      <Titulo detalle="Estados contables, memorias y resoluciones, publicados con su huella de integridad: el archivo que descargás es idéntico al aprobado.">
        Estados contables y documentos oficiales
      </Titulo>
      {query.isError && (
        <div className="mt-6">
          <Alert tone="danger">{toProblem(query.error).detail}</Alert>
        </div>
      )}
      {query.isPending && <Cargando />}
      {query.data && grupos.size === 0 && (
        <p className="mt-8 text-ink-muted">Todavía no hay documentos publicados.</p>
      )}
      <div className="mt-8 grid gap-10">
        {[...grupos.entries()].map(([tipo, docs]) => (
          <section key={tipo} aria-label={tipo}>
            <h2 className="text-lg font-semibold text-brand-900">{tipo}</h2>
            <ul className="mt-2 divide-y divide-line border-y border-line">
              {docs.map((d) => (
                <DocumentoItem key={d.slug} doc={d} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}

export function ContactoPage() {
  const query = useQuery({ queryKey: ['sitio'], queryFn: fetchSitio })
  const c = query.data?.contacto
  const sinDatos = c && !c.domicilio && !c.telefono && !c.email
  return (
    <div className="mx-auto max-w-4xl">
      <Titulo detalle="Si tiene alguna pregunta, no dude en ponerse en contacto con nosotros.">
        Contacto
      </Titulo>
      {query.isError && (
        <div className="mt-6">
          <Alert tone="danger">{toProblem(query.error).detail}</Alert>
        </div>
      )}
      {query.isPending && <Cargando />}
      {sinDatos && (
        <p className="mt-8 text-ink-muted">Los datos de contacto se publicarán próximamente.</p>
      )}
      {c && !sinDatos && (
        <dl className="mt-8 grid gap-x-10 border-t border-line sm:grid-cols-3">
          {c.domicilio && (
            <div className="border-b border-line py-5">
              <dt className="flex items-center gap-2 text-sm text-ink-muted">
                <MapPin aria-hidden="true" className="size-4" strokeWidth={2.25} />
                Oficinas
              </dt>
              <dd className="mt-1 font-semibold text-ink">{c.domicilio}</dd>
            </div>
          )}
          {c.telefono && (
            <div className="border-b border-line py-5">
              <dt className="flex items-center gap-2 text-sm text-ink-muted">
                <Phone aria-hidden="true" className="size-4" strokeWidth={2.25} />
                Teléfono
              </dt>
              <dd className="mt-1 font-semibold tabular-nums">
                <a href={`tel:${c.telefono.replace(/[^\d+]/g, '')}`}>{c.telefono}</a>
              </dd>
            </div>
          )}
          {c.email && (
            <div className="border-b border-line py-5">
              <dt className="flex items-center gap-2 text-sm text-ink-muted">
                <Mail aria-hidden="true" className="size-4" strokeWidth={2.25} />
                Correo
              </dt>
              <dd className="mt-1 font-semibold break-all">
                <a href={`mailto:${c.email}`}>{c.email}</a>
              </dd>
            </div>
          )}
        </dl>
      )}
    </div>
  )
}
