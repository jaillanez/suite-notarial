import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, ExternalLink, Plus, Save, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import {
  fetchNovedades,
  fetchPortada,
  guardarPortada,
  type Distribucion,
  type FilaPortada,
  type Novedad,
  type Portada,
} from './api'
import { ANCHOS, DISTRIBUCION, fechaLarga } from './labels'

const MAX_DESTACADAS = 5
const MAX_FILAS = 8
const SPAN: Record<number, string> = {
  1: 'sm:col-span-1',
  2: 'sm:col-span-2',
  3: 'sm:col-span-3',
  4: 'sm:col-span-4',
}

type Armado = Pick<Portada, 'destacadas' | 'filas'>

function mover<T>(lista: T[], i: number, paso: number): T[] {
  const j = i + paso
  if (j < 0 || j >= lista.length) return lista
  const copia = [...lista]
  ;[copia[i], copia[j]] = [copia[j] as T, copia[i] as T]
  return copia
}

/** Dibujo de la distribución: cuatro columnas con el ancho de cada nota. */
function Esquema({ distribucion }: { distribucion: Distribucion }) {
  return (
    <span aria-hidden="true" className="grid h-5 w-12 grid-cols-4 gap-0.5">
      {ANCHOS[distribucion].map((a, i) => (
        <span
          key={i}
          className="rounded-[2px] bg-current"
          style={{ gridColumn: `span ${String(a)}` }}
        />
      ))}
    </span>
  )
}

function ElegirDistribucion({
  valor,
  onChange,
  fila,
}: {
  valor: Distribucion
  onChange: (d: Distribucion) => void
  fila: number
}) {
  return (
    <fieldset>
      <legend className="sr-only">Distribución de la fila {fila}</legend>
      <div className="flex flex-wrap gap-1.5">
        {(Object.keys(ANCHOS) as Distribucion[]).map((d) => (
          <label
            key={d}
            title={DISTRIBUCION[d]}
            className={`inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-control border px-3 text-sm font-medium transition-colors duration-150 ease-out-quint has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-action-600 ${
              valor === d
                ? 'border-brand-800 bg-brand-800 text-white'
                : 'border-line-strong bg-surface text-brand-800 hover:bg-brand-50'
            }`}
          >
            <input
              type="radio"
              name={`distribucion-${String(fila)}`}
              value={d}
              checked={valor === d}
              onChange={() => {
                onChange(d)
              }}
              className="sr-only"
            />
            <Esquema distribucion={d} />
            <span className="tabular-nums">{d}</span>
            <span className="sr-only">: {DISTRIBUCION[d]}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function opciones(
  notas: Novedad[],
  usadas: Set<string>,
  propia: string | null,
  vacio: string,
): { value: string; label: string; disabled?: boolean }[] {
  return [
    { value: '', label: vacio },
    ...notas.map((n) => ({
      value: n.id,
      label:
        n.estado === 'PUBLICADO'
          ? n.titulo
          : `${n.titulo} (${n.estado === 'BORRADOR' ? 'borrador' : 'archivada'}: no se ve)`,
      disabled: usadas.has(n.id) && n.id !== propia,
    })),
  ]
}

function Editor({ inicial, notas }: { inicial: Portada; notas: Novedad[] }) {
  const queryClient = useQueryClient()
  const [armado, setArmado] = useState<Armado>({
    destacadas: inicial.destacadas,
    filas: inicial.filas,
  })
  const [guardada, setGuardada] = useState(inicial)
  const cambios =
    JSON.stringify(armado) !==
    JSON.stringify({ destacadas: guardada.destacadas, filas: guardada.filas })
  const guardar = useMutation({
    mutationFn: () => guardarPortada(armado),
    onSuccess: async (p) => {
      setGuardada(p)
      queryClient.setQueryData(['cms', 'portada'], p)
      await queryClient.invalidateQueries({ queryKey: ['sitio'] })
    },
  })
  const porId = new Map(notas.map((n) => [n.id, n]))
  const enFilas = new Set(armado.filas.flatMap((f) => f.notas).filter((n): n is string => !!n))
  const destacadas = new Set(armado.destacadas)
  const ocultas = [...destacadas, ...enFilas].filter(
    (id) => porId.get(id)?.estado !== 'PUBLICADO',
  ).length

  const setFila = (i: number, fila: FilaPortada) => {
    setArmado((a) => ({ ...a, filas: a.filas.map((f, j) => (j === i ? fila : f)) }))
  }

  return (
    <div className="grid gap-6">
      {ocultas > 0 && (
        <Alert tone="warning">
          {ocultas === 1
            ? 'Una nota del armado no está publicada: no se ve en el sitio hasta que la publiques.'
            : `${String(ocultas)} notas del armado no están publicadas: no se ven en el sitio hasta que las publiques.`}
        </Alert>
      )}

      <Panel
        title="Destacadas"
        description="Encabezan la portada, una a la vez y con la imagen grande. La primera es la que se ve al entrar; el lector pasa a las demás con las flechas."
        actions={
          <Button
            icon={Plus}
            disabled={armado.destacadas.length >= MAX_DESTACADAS}
            onClick={() => {
              setArmado((a) => ({ ...a, destacadas: [...a.destacadas, ''] }))
            }}
          >
            Agregar destacada
          </Button>
        }
      >
        {armado.destacadas.length === 0 ? (
          <p className="px-5 py-8 text-center text-ink-muted sm:px-6">
            Sin destacadas: la portada abre con la fila de servicios. Agregá al menos una para que
            la Caja tenga su nota principal.
          </p>
        ) : (
          <ol className="divide-y divide-line">
            {armado.destacadas.map((id, i) => (
              <li
                key={i}
                className="grid gap-3 px-5 py-4 sm:grid-cols-[2rem_1fr_auto] sm:items-end sm:px-6"
              >
                <span className="text-lg font-semibold text-brand-900 tabular-nums sm:pb-2.5">
                  {i + 1}
                </span>
                <Select
                  label={i === 0 ? 'Nota principal' : `Destacada ${String(i + 1)}`}
                  value={id}
                  onChange={(e) => {
                    const valor = e.target.value
                    setArmado((a) => ({
                      ...a,
                      destacadas: a.destacadas.map((d, j) => (j === i ? valor : d)),
                    }))
                  }}
                  options={opciones(notas, destacadas, id, 'Elegí una nota…')}
                />
                <div className="flex gap-1">
                  <Button
                    variant="ghost"
                    icon={ArrowUp}
                    className="w-11 px-0"
                    aria-label={`Subir la destacada ${String(i + 1)}`}
                    disabled={i === 0}
                    onClick={() => {
                      setArmado((a) => ({ ...a, destacadas: mover(a.destacadas, i, -1) }))
                    }}
                  />
                  <Button
                    variant="ghost"
                    icon={ArrowDown}
                    className="w-11 px-0"
                    aria-label={`Bajar la destacada ${String(i + 1)}`}
                    disabled={i === armado.destacadas.length - 1}
                    onClick={() => {
                      setArmado((a) => ({ ...a, destacadas: mover(a.destacadas, i, 1) }))
                    }}
                  />
                  <Button
                    variant="ghost"
                    icon={Trash2}
                    className="w-11 px-0"
                    aria-label={`Quitar la destacada ${String(i + 1)}`}
                    onClick={() => {
                      setArmado((a) => ({
                        ...a,
                        destacadas: a.destacadas.filter((_, j) => j !== i),
                      }))
                    }}
                  />
                </div>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <Panel
        title="Filas de noticias"
        description="Debajo de los servicios online. Cada fila reparte cuatro columnas: elegí la distribución y qué nota va en cada espacio. Una nota puede estar una sola vez en las filas."
        actions={
          <Button
            icon={Plus}
            disabled={armado.filas.length >= MAX_FILAS}
            onClick={() => {
              setArmado((a) => ({
                ...a,
                filas: [...a.filas, { distribucion: '2+1+1', notas: [null, null, null] }],
              }))
            }}
          >
            Agregar fila
          </Button>
        }
      >
        {armado.filas.length === 0 ? (
          <p className="px-5 py-8 text-center text-ink-muted sm:px-6">
            Sin filas: debajo de los servicios no se muestran noticias.
          </p>
        ) : (
          <ol className="divide-y divide-line">
            {armado.filas.map((fila, i) => {
              const anchos = ANCHOS[fila.distribucion]
              return (
                <li key={i} className="grid gap-4 px-5 py-5 sm:px-6">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <h3 className="font-semibold text-ink">
                      Fila {i + 1}
                      <span className="ml-2 text-sm font-normal text-ink-muted">
                        {DISTRIBUCION[fila.distribucion]}
                      </span>
                    </h3>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        icon={ArrowUp}
                        className="w-11 px-0"
                        aria-label={`Subir la fila ${String(i + 1)}`}
                        disabled={i === 0}
                        onClick={() => {
                          setArmado((a) => ({ ...a, filas: mover(a.filas, i, -1) }))
                        }}
                      />
                      <Button
                        variant="ghost"
                        icon={ArrowDown}
                        className="w-11 px-0"
                        aria-label={`Bajar la fila ${String(i + 1)}`}
                        disabled={i === armado.filas.length - 1}
                        onClick={() => {
                          setArmado((a) => ({ ...a, filas: mover(a.filas, i, 1) }))
                        }}
                      />
                      <Button
                        variant="ghost"
                        icon={Trash2}
                        className="w-11 px-0"
                        aria-label={`Quitar la fila ${String(i + 1)}`}
                        onClick={() => {
                          setArmado((a) => ({ ...a, filas: a.filas.filter((_, j) => j !== i) }))
                        }}
                      />
                    </div>
                  </div>
                  <ElegirDistribucion
                    fila={i + 1}
                    valor={fila.distribucion}
                    onChange={(d) => {
                      // Se conservan las notas elegidas en el orden en que estaban.
                      const espacios = ANCHOS[d].length
                      const notasFila = fila.notas
                        .filter((n): n is string => !!n)
                        .slice(0, espacios)
                      setFila(i, {
                        distribucion: d,
                        notas: [
                          ...notasFila,
                          ...Array<null>(espacios - notasFila.length).fill(null),
                        ],
                      })
                    }}
                  />
                  <div className="grid gap-3 rounded-control bg-surface-sunken p-3 sm:grid-cols-4">
                    {anchos.map((ancho, k) => {
                      const id = fila.notas[k] ?? null
                      return (
                        <div
                          key={k}
                          className={`rounded-control border border-dashed border-line-strong bg-surface p-3 ${SPAN[ancho] ?? ''}`}
                        >
                          <Select
                            label={`Espacio ${String(k + 1)} · ${String(ancho)} ${ancho === 1 ? 'columna' : 'columnas'}`}
                            value={id ?? ''}
                            onChange={(e) => {
                              const valor = e.target.value || null
                              setFila(i, {
                                ...fila,
                                notas: fila.notas.map((n, j) => (j === k ? valor : n)),
                              })
                            }}
                            options={opciones(notas, enFilas, id, 'Espacio libre')}
                          />
                        </div>
                      )
                    })}
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </Panel>

      <div className="sticky bottom-0 z-10 -mx-4 border-t border-line bg-surface/95 px-4 py-3 backdrop-blur-sm sm:mx-0 sm:rounded-panel sm:border sm:shadow-panel">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-ink-muted" aria-live="polite">
            {cambios
              ? 'Hay cambios sin guardar: el sitio sigue mostrando la portada anterior.'
              : guardada.actualizada
                ? `Guardada el ${fechaLarga(guardada.actualizada)}${guardada.actualizada_por ? ` por ${guardada.actualizada_por}` : ''}.`
                : 'Todavía no se armó la portada: el sitio muestra las últimas notas publicadas.'}
          </p>
          <div className="flex flex-wrap gap-2">
            <Link
              to="/sitio"
              target="_blank"
              className="inline-flex min-h-11 items-center gap-2 rounded-control px-3 text-sm font-semibold no-underline hover:bg-brand-50"
            >
              <ExternalLink aria-hidden="true" className="size-4" strokeWidth={2.25} />
              Ver el sitio
            </Link>
            <Button
              variant="primary"
              icon={Save}
              busy={guardar.isPending}
              busyLabel="Guardando…"
              disabled={!cambios || armado.destacadas.some((d) => !d)}
              onClick={() => {
                guardar.mutate()
              }}
            >
              Guardar portada
            </Button>
          </div>
        </div>
        {guardar.isError && (
          <div className="mt-3">
            <Alert tone="danger">{toProblem(guardar.error).detail}</Alert>
          </div>
        )}
      </div>
    </div>
  )
}

export function PortadaAdmin() {
  const portada = useQuery({ queryKey: ['cms', 'portada'], queryFn: fetchPortada })
  const notas = useQuery({
    queryKey: ['cms', 'novedades', 'para-portada'],
    queryFn: () => fetchNovedades({ page: 1, pageSize: 100, estado: '' }),
  })
  const error = portada.error ?? notas.error
  if (error) return <Alert tone="danger">{toProblem(error).detail}</Alert>
  if (!portada.data || !notas.data) {
    return (
      <div aria-busy="true" className="grid gap-6">
        <span className="sr-only">Cargando el armado de la portada…</span>
        <span className="block h-40 animate-pulse rounded-panel bg-brand-50" />
        <span className="block h-64 animate-pulse rounded-panel bg-brand-50" />
      </div>
    )
  }
  // Publicadas primero: son las que se ven en el sitio.
  const ordenadas = [...notas.data.items].sort(
    (a, b) => Number(b.estado === 'PUBLICADO') - Number(a.estado === 'PUBLICADO'),
  )
  return <Editor inicial={portada.data} notas={ordenadas} />
}
