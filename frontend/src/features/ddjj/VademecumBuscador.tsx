import { Check, Search } from 'lucide-react'
import { useId, useMemo, useState, type KeyboardEvent } from 'react'

import type { CategoriaActo, VademecumActo } from './api'
import { CATEGORIA, MOTIVO_EXENCION } from './labels'
import {
  buscarEnVademecum,
  FUERA,
  SIN_EFECTO,
  textoDeEleccion,
  type EleccionVademecum,
} from './vademecum'

const GRUPOS: { categoria: CategoriaActo; titulo: string }[] = [
  { categoria: 'ESCRITURA_CON_VALOR', titulo: 'Aporte variable' },
  { categoria: 'OTRO_ACTO', titulo: 'Aporte fijo mayor' },
  { categoria: 'ACTA_O_PODER', titulo: 'Aporte fijo menor' },
  { categoria: 'EXENTO', titulo: 'Exentos o sin aporte' },
]

interface Opcion {
  clave: string
  texto: string
  eleccion: EleccionVademecum
}

/**
 * Buscador del vademécum de aportes (combobox ARIA 1.2): se escribe parte del nombre o un
 * sinónimo, se elige con flechas y Enter o con un toque. La lista queda dentro del flujo del
 * formulario (no flota) para que no la recorte el cuerpo desplazable del diálogo.
 */
export function VademecumBuscador({
  actos,
  eleccion,
  onElegir,
  error,
}: {
  actos: VademecumActo[]
  eleccion: EleccionVademecum | null
  onElegir: (eleccion: EleccionVademecum) => void
  error?: string
}) {
  const id = useId()
  const listaId = `${id}-lista`
  const ayudaId = `${id}-ayuda`
  const [consulta, setConsulta] = useState<string | null>(null)
  const [activa, setActiva] = useState(0)
  const abierta = consulta !== null

  const grupos = useMemo(() => {
    const encontrados = buscarEnVademecum(actos, consulta ?? '')
    return GRUPOS.map((g) => ({
      ...g,
      opciones: encontrados
        .filter((a) => a.categoria === g.categoria)
        .map<Opcion>((a) => ({
          clave: a.id,
          texto: a.nombre,
          eleccion: { tipo: 'vademecum', acto: a },
        })),
    })).filter((g) => g.opciones.length > 0)
  }, [actos, consulta])
  const salidas: Opcion[] = [
    { clave: 'sin_efecto', texto: SIN_EFECTO, eleccion: { tipo: 'sin_efecto' } },
    { clave: 'fuera', texto: FUERA, eleccion: { tipo: 'fuera' } },
  ]
  const opciones = [...grupos.flatMap((g) => g.opciones), ...salidas]
  const indice = Math.min(activa, opciones.length - 1)
  const opcionId = (clave: string) => `${id}-op-${clave}`

  const elegir = (o: Opcion) => {
    onElegir(o.eleccion)
    setConsulta(null)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!abierta) {
        setConsulta('')
        setActiva(0)
        return
      }
      const paso = e.key === 'ArrowDown' ? 1 : -1
      setActiva((indice + paso + opciones.length) % opciones.length)
    } else if (e.key === 'Enter' && abierta) {
      e.preventDefault()
      const o = opciones[indice]
      if (o) elegir(o)
    } else if (e.key === 'Escape' && abierta) {
      // Cierra la lista sin cerrar el diálogo.
      e.preventDefault()
      e.stopPropagation()
      setConsulta(null)
    }
  }
  const elegido = eleccion?.tipo === 'vademecum' ? eleccion.acto : null
  const seleccionada = (o: Opcion) =>
    o.eleccion.tipo === 'vademecum'
      ? elegido?.id === o.eleccion.acto.id
      : eleccion?.tipo === o.eleccion.tipo

  const renderOpcion = (o: Opcion) => {
    const i = opciones.indexOf(o)
    return (
      <li
        key={o.clave}
        id={opcionId(o.clave)}
        role="option"
        aria-selected={seleccionada(o)}
        onMouseDown={(e) => {
          // Que el campo no pierda el foco antes de elegir.
          e.preventDefault()
        }}
        onClick={() => {
          elegir(o)
        }}
        onMouseMove={() => {
          if (i !== indice) setActiva(i)
        }}
        className={`flex min-h-11 cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm text-ink ${i === indice ? 'bg-brand-50' : ''}`}
      >
        <span>{o.texto}</span>
        {seleccionada(o) && (
          <Check aria-hidden="true" className="size-4 shrink-0 text-brand-800" strokeWidth={2.25} />
        )}
      </li>
    )
  }

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-ink">
        Acto (vademécum de aportes)
      </label>
      <div className="relative mt-1.5">
        <input
          id={id}
          role="combobox"
          aria-expanded={abierta}
          aria-controls={listaId}
          aria-autocomplete="list"
          aria-activedescendant={
            abierta && opciones[indice] ? opcionId(opciones[indice].clave) : undefined
          }
          aria-describedby={ayudaId}
          aria-invalid={error ? true : undefined}
          autoComplete="off"
          placeholder="Escribí: venta, poder, usufructo…"
          value={consulta ?? textoDeEleccion(eleccion)}
          onChange={(e) => {
            setConsulta(e.target.value)
            setActiva(0)
          }}
          onFocus={(e) => {
            e.target.select()
          }}
          onClick={() => {
            if (!abierta) {
              setConsulta('')
              setActiva(0)
            }
          }}
          onBlur={() => {
            setConsulta(null)
          }}
          onKeyDown={onKeyDown}
          className={`block min-h-11 w-full rounded-control border bg-surface pr-3 pl-10 text-base text-ink placeholder:text-ink-subtle transition-colors duration-150 ease-out-quint focus-visible:border-action-600 ${error ? 'border-danger-700' : 'border-line-strong'}`}
        />
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-muted"
          strokeWidth={2.25}
        />
      </div>
      {abierta && (
        <div
          id={listaId}
          role="listbox"
          aria-label="Actos del vademécum"
          className="mt-1 max-h-72 overflow-y-auto rounded-control border border-line-strong bg-surface"
        >
          {grupos.length === 0 && (
            <p className="px-3 py-2.5 text-sm text-ink-muted">
              Ningún acto coincide. Si no está en el vademécum, elegí «{FUERA}».
            </p>
          )}
          {grupos.map((g) => (
            <ul key={g.categoria} role="group" aria-labelledby={`${id}-g-${g.categoria}`}>
              <li
                id={`${id}-g-${g.categoria}`}
                role="presentation"
                className="sticky top-0 bg-surface-sunken px-3 py-1.5 text-xs font-semibold text-ink-muted"
              >
                {g.titulo}
              </li>
              {g.opciones.map(renderOpcion)}
            </ul>
          ))}
          <ul role="group" aria-label="Fuera del vademécum" className="border-t border-line">
            {salidas.map(renderOpcion)}
          </ul>
        </div>
      )}
      <p id={ayudaId} className="mt-1.5 text-sm text-ink-muted">
        {ayudaDe(eleccion)}
      </p>
      {error && <p className="mt-1.5 text-sm font-medium text-danger-700">{error}</p>}
    </div>
  )
}

function ayudaDe(eleccion: EleccionVademecum | null): string {
  if (!eleccion) return 'El acto define cómo aporta: no hace falta elegir el tipo.'
  if (eleccion.tipo === 'sin_efecto')
    return 'Se declara para no dejar huecos en la numeración y no aporta.'
  if (eleccion.tipo === 'fuera')
    return 'Elegí cómo aporta. El acto queda marcado para que la Caja lo revise.'
  const { acto } = eleccion
  const como =
    acto.categoria === 'EXENTO' && acto.motivo_exencion
      ? `Exento · ${MOTIVO_EXENCION[acto.motivo_exencion]}`
      : CATEGORIA[acto.categoria].label
  return acto.aclaracion ? `${como}. ${acto.aclaracion}` : `${como}.`
}
