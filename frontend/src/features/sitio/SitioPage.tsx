import { useQuery } from '@tanstack/react-query'
import { ArrowRight, ChevronLeft, ChevronRight, FileDown } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import fotoInstitucional from '../../assets/sitio/firma-escritura.webp'
import { Alert } from '../../components/ui/Alert'
import { toProblem } from '../../lib/api'
import { fetchSitio, type Distribucion, type NovedadResumen } from '../cms/api'
import { ANCHOS, fechaLarga, rutaLocal } from '../cms/labels'
import { SERVICIOS } from './menu'

const SPAN: Record<number, string> = {
  1: 'md:col-span-1',
  2: 'md:col-span-2',
  3: 'md:col-span-3',
  4: 'md:col-span-4',
}

function Meta({ nota }: { nota: NovedadResumen }) {
  return (
    <p className="text-sm text-ink-muted">
      <Link
        to={`/sitio/novedades?seccion=${nota.seccion}`}
        className="font-medium text-brand-800 no-underline hover:underline"
      >
        {nota.seccion_texto}
      </Link>
      <span aria-hidden="true"> · </span>
      <time dateTime={nota.fecha_publicacion} className="tabular-nums">
        {fechaLarga(nota.fecha_publicacion)}
      </time>
    </p>
  )
}

/** Una nota de la portada. El tamaño del título y de la imagen sigue al ancho que le dio el
 * armado (de 1 a 4 columnas). Sin imagen, la nota es solo texto: nunca una foto repetida. */
function Nota({ nota, ancho }: { nota: NovedadResumen; ancho: number }) {
  const grande = ancho >= 2
  const enlace = `/sitio/novedades/${nota.slug}`
  return (
    <article className={`group grid content-start gap-3 ${SPAN[ancho] ?? ''}`}>
      {nota.imagen_url && (
        <Link
          to={enlace}
          tabIndex={-1}
          aria-hidden="true"
          className="block overflow-hidden rounded-panel bg-brand-50"
        >
          <img
            src={nota.imagen_url}
            alt=""
            loading="lazy"
            className={`w-full object-cover transition-transform duration-500 ease-out-quint group-hover:scale-[1.02] ${
              grande ? 'aspect-[16/9]' : 'aspect-[3/2]'
            }`}
          />
        </Link>
      )}
      <h3
        className={`font-semibold text-balance text-ink ${
          grande ? 'text-xl sm:text-2xl sm:leading-tight' : 'text-lg leading-snug'
        }`}
      >
        <Link
          to={enlace}
          className="text-inherit no-underline hover:text-brand-800 hover:underline"
        >
          {nota.titulo}
        </Link>
      </h3>
      {nota.resumen && (
        <p className={`text-ink-muted ${grande ? 'max-w-[60ch] text-base' : 'text-sm'}`}>
          {nota.resumen}
        </p>
      )}
      <Meta nota={nota} />
    </article>
  )
}

function Fila({ distribucion, notas }: { distribucion: Distribucion; notas: NovedadResumen[] }) {
  const anchos = ANCHOS[distribucion]
  return (
    <div className="grid gap-x-8 gap-y-10 border-t border-line pt-8 md:grid-cols-4">
      {notas.map((n, i) => (
        <Nota key={n.slug} nota={n} ancho={anchos[i] ?? 1} />
      ))}
    </div>
  )
}

/** Destacadas: una a la vez, con imagen grande y el título al lado. Se pasa a mano (sin
 * avance automático): el lector decide cuándo cambiar. */
function Destacadas({ notas }: { notas: NovedadResumen[] }) {
  const [actual, setActual] = useState(0)
  // La animación acompaña el cambio que pidió el lector; al cargar, la nota ya está ahí.
  const [cambio, setCambio] = useState(false)
  const nota = notas[Math.min(actual, notas.length - 1)]
  if (!nota) return null
  const varias = notas.length > 1
  const mover = (paso: number) => {
    setCambio(true)
    setActual((i) => (i + paso + notas.length) % notas.length)
  }
  const enlace = `/sitio/novedades/${nota.slug}`
  return (
    <section aria-roledescription="carrusel" aria-label="Notas destacadas" className="pb-10">
      <div
        key={nota.slug}
        aria-live="polite"
        className={`grid gap-6 ${cambio ? 'animate-[aparecer_420ms_var(--ease-out-quint)]' : ''} lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] lg:items-center lg:gap-10`}
      >
        <Link
          to={enlace}
          tabIndex={-1}
          aria-hidden="true"
          className="block overflow-hidden rounded-panel bg-brand-50"
        >
          <img
            src={nota.imagen_url ?? fotoInstitucional}
            alt=""
            className="aspect-[16/10] w-full object-cover"
          />
        </Link>
        <div className="grid content-center gap-4">
          <Meta nota={nota} />
          <h1 className="text-3xl leading-tight font-semibold tracking-tight text-balance text-brand-900 sm:text-[2.5rem]">
            <Link to={enlace} className="text-inherit no-underline hover:underline">
              {nota.titulo}
            </Link>
          </h1>
          {nota.resumen && <p className="max-w-[55ch] text-lg text-ink-muted">{nota.resumen}</p>}
          <Link
            to={enlace}
            className="inline-flex min-h-11 items-center gap-1.5 justify-self-start font-medium"
          >
            Leer la nota
            <ArrowRight aria-hidden="true" className="size-4" strokeWidth={2.25} />
          </Link>
        </div>
      </div>
      {varias && (
        <div className="mt-6 flex items-center gap-3 lg:justify-end">
          <button
            type="button"
            onClick={() => {
              mover(-1)
            }}
            aria-label="Nota destacada anterior"
            className="inline-flex size-11 items-center justify-center rounded-control border border-line-strong bg-surface text-brand-800 transition-colors duration-150 ease-out-quint hover:border-brand-700 hover:bg-brand-50"
          >
            <ChevronLeft aria-hidden="true" className="size-5" strokeWidth={2.25} />
          </button>
          <ol className="flex gap-1.5" aria-label="Elegir nota destacada">
            {notas.map((n, i) => (
              <li key={n.slug}>
                <button
                  type="button"
                  aria-label={`Destacada ${String(i + 1)} de ${String(notas.length)}: ${n.titulo}`}
                  aria-current={i === actual}
                  onClick={() => {
                    setCambio(true)
                    setActual(i)
                  }}
                  className="flex h-11 w-7 items-center justify-center"
                >
                  <span
                    className={`block h-1 rounded-full transition-all duration-300 ease-out-quint ${
                      i === actual ? 'w-6 bg-brand-800' : 'w-3 bg-line-strong'
                    }`}
                  />
                </button>
              </li>
            ))}
          </ol>
          <button
            type="button"
            onClick={() => {
              mover(1)
            }}
            aria-label="Nota destacada siguiente"
            className="inline-flex size-11 items-center justify-center rounded-control border border-line-strong bg-surface text-brand-800 transition-colors duration-150 ease-out-quint hover:border-brand-700 hover:bg-brand-50"
          >
            <ChevronRight aria-hidden="true" className="size-5" strokeWidth={2.25} />
          </button>
        </div>
      )}
    </section>
  )
}

function Servicios() {
  return (
    <section
      aria-labelledby="servicios"
      className="mb-12 rounded-panel border border-line bg-surface shadow-panel"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-5 py-4 sm:px-6">
        <h2 id="servicios" className="text-lg font-semibold text-brand-900">
          Servicios online
        </h2>
        <p className="text-sm text-ink-muted">
          Trámites del afiliado, desde la escribanía o el celular.
        </p>
      </div>
      <ul className="grid sm:grid-cols-4 lg:grid-cols-7">
        {SERVICIOS.map(({ to, label, detalle, icon: Icono }) => (
          <li
            key={label}
            className="border-line [&:not(:last-child)]:border-b sm:border-r lg:border-b-0"
          >
            <Link
              to={to}
              className="flex h-full min-h-14 items-center gap-3 px-4 py-3 text-ink no-underline transition-colors duration-150 ease-out-quint hover:bg-brand-50 sm:min-h-28 sm:flex-col sm:items-start sm:gap-2 sm:py-4"
            >
              <Icono
                aria-hidden="true"
                className="size-6 shrink-0 text-brand-800"
                strokeWidth={2}
              />
              <span className="text-sm leading-snug font-semibold">{label}</span>
              <span className="hidden text-xs text-ink-muted sm:block">{detalle}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function SitioPage() {
  const query = useQuery({ queryKey: ['sitio'], queryFn: fetchSitio })
  const sitio = query.data

  if (query.isError) return <Alert tone="danger">{toProblem(query.error).detail}</Alert>
  if (!sitio) {
    return (
      <div aria-busy="true" aria-live="polite" className="grid gap-6">
        <span className="sr-only">Cargando la portada…</span>
        <span className="block aspect-[16/7] animate-pulse rounded-panel bg-brand-50" />
        <span className="block h-28 animate-pulse rounded-panel bg-brand-50" />
      </div>
    )
  }

  const { destacadas, filas } = sitio.portada
  const documentos = sitio.documentos.slice(0, 4)
  return (
    <div>
      {destacadas.length > 0 ? (
        <Destacadas notas={destacadas} />
      ) : (
        <h1 className="pb-8 text-3xl font-semibold tracking-tight text-brand-900">
          Caja Notarial de San Juan
        </h1>
      )}

      <Servicios />

      {filas.length > 0 && (
        <section aria-labelledby="noticias" className="grid gap-6">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2 id="noticias" className="text-xl font-semibold text-brand-900">
              Novedades
            </h2>
            <Link
              to="/sitio/novedades"
              className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium"
            >
              Todas las novedades
              <ArrowRight aria-hidden="true" className="size-4" strokeWidth={2.25} />
            </Link>
          </div>
          {filas.map((f, i) => (
            <Fila key={i} distribucion={f.distribucion} notas={f.notas} />
          ))}
        </section>
      )}
      {destacadas.length === 0 && filas.length === 0 && (
        <p className="text-ink-muted">Todavía no hay novedades publicadas.</p>
      )}

      <div className="mt-14 grid gap-12 border-t border-line pt-10 lg:grid-cols-2">
        <section aria-labelledby="autoridades">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2 id="autoridades" className="text-xl font-semibold text-brand-900">
              Autoridades
            </h2>
            <Link
              to="/sitio/autoridades"
              className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium"
            >
              Consejo completo
              <ArrowRight aria-hidden="true" className="size-4" strokeWidth={2.25} />
            </Link>
          </div>
          {sitio.autoridades.length === 0 ? (
            <p className="mt-4 text-ink-muted">
              La nómina de autoridades se publicará próximamente.
            </p>
          ) : (
            <dl className="mt-4 grid gap-x-8 gap-y-4 sm:grid-cols-2">
              {sitio.autoridades.slice(0, 4).map((a) => (
                <div key={a.id}>
                  <dt className="text-sm text-ink-muted">{a.cargo}</dt>
                  <dd className="font-semibold text-ink">{a.nombre}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
        <section aria-labelledby="documentos">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2 id="documentos" className="text-xl font-semibold text-brand-900">
              Estados contables y documentos
            </h2>
            <Link
              to="/sitio/documentos"
              className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium"
            >
              Todos los documentos
              <ArrowRight aria-hidden="true" className="size-4" strokeWidth={2.25} />
            </Link>
          </div>
          {documentos.length === 0 ? (
            <p className="mt-4 text-ink-muted">Todavía no hay documentos publicados.</p>
          ) : (
            <ul className="mt-2 divide-y divide-line">
              {documentos.map((d) => (
                <li key={d.slug} className="flex items-center gap-4 py-3">
                  <span className="w-14 text-lg font-semibold text-brand-900 tabular-nums">
                    {d.ejercicio}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium text-ink">{d.titulo}</span>
                    <span className="block text-sm text-ink-muted">{d.tipo_texto}</span>
                  </span>
                  <a
                    href={rutaLocal(d.url)}
                    aria-label={`Descargar ${d.titulo} ${String(d.ejercicio)} (PDF)`}
                    className="inline-flex size-11 shrink-0 items-center justify-center rounded-control border border-line-strong text-brand-800 hover:border-brand-700 hover:bg-brand-50"
                  >
                    <FileDown aria-hidden="true" className="size-4" strokeWidth={2.25} />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
