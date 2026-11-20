import { useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  CircleCheck,
  CircleDashed,
  CircleX,
  LoaderCircle,
  Plus,
  Save,
  Trash2,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Select } from '../../components/ui/Select'
import { toProblem, type Problem } from '../../lib/api'
import { formatMoney } from '../../lib/decimal'
import { CARGO, matriculaTexto, todayIso } from '../padron/labels'
import { actoCompleto, actoInput, actoSiguiente, actoSugerido, type ActoForm } from './acto'
import { ActoCampos } from './ActoCampos'
import { agregarActo, type CategoriaActo, type DeclaracionDetalle, type VademecumActo } from './api'
import { rangoPeriodo } from './labels'
import { useVerificacionActo } from './verificacion'
import {
  FUERA,
  SIN_EFECTO,
  alElegir,
  eleccionDe,
  normalizar,
  textoDeEleccion,
  useVademecumDelPeriodo,
  type EleccionVademecum,
} from './vademecum'

/** Un renglón de la planilla: el acto tal como se tipea y en qué quedó. */
interface Renglon {
  clave: number
  form: ActoForm
  /** Lo escrito en la celda «Acto» cuando todavía no coincide con un acto del vademécum. */
  consulta: string
  /** El editor completo del acto, abierto bajo el renglón. */
  abierto: boolean
  error: Problem | null
}

/** Columnas editables, en el orden en que se recorren con Enter. */
const COLUMNAS = [
  'protocolo',
  'numero',
  'folio',
  'fecha',
  'acto',
  'tipo',
  'precio',
  'avaluo',
  'base',
] as const
type Columna = (typeof COLUMNAS)[number]

const CELDA =
  'block min-h-11 w-full min-w-0 rounded-control border bg-surface px-2 text-sm text-ink tabular-nums placeholder:text-ink-subtle transition-colors duration-150 ease-out-quint focus-visible:border-action-600 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-subtle'

/** Columnas de la grilla desde 640px; bajo ese ancho cada renglón se apila con sus etiquetas.
 * Con vademécum van precio y avalúo; sin él, una sola base imponible y más lugar para el acto. */
const GRILLA_VADEMECUM =
  'sm:grid sm:grid-cols-[1.25rem_5rem_4.25rem_3.5rem_9.5rem_minmax(7rem,1fr)_7.5rem_6rem_6rem_5.75rem] sm:items-start sm:gap-x-1.5'
const GRILLA_BASE =
  'sm:grid sm:grid-cols-[1.25rem_5rem_4.25rem_3.5rem_9.5rem_minmax(9rem,1fr)_7.5rem_8rem_5.75rem] sm:items-start sm:gap-x-1.5'

/** Tipo de aporte, con los nombres de la planilla de la Caja. */
const TIPOS: { value: CategoriaActo; label: string }[] = [
  { value: 'ESCRITURA_CON_VALOR', label: 'Variable' },
  { value: 'OTRO_ACTO', label: 'Fijo mayor' },
  { value: 'ACTA_O_PODER', label: 'Fijo menor' },
  { value: 'EXENTO', label: 'Exento' },
  { value: 'SIN_EFECTO', label: 'Sin efecto' },
]

/** Protocolo abreviado: la columna es angosta y el nombre completo va en el lector. */
const PROTOCOLO_CORTO = { GENERAL: 'Gral.', AUXILIAR: 'Aux.' } as const

/** Con vademécum, el tipo lo fija el acto elegido; a mano solo para uno que no está en él. */
function eligeTipo(form: ActoForm, conVademecum: boolean): boolean {
  return !conVademecum || form.fuera_de_vademecum
}

/** Qué elige la celda «Acto» según lo escrito: un acto del vademécum o una de las salidas. */
function eleccionPorTexto(texto: string, actos: VademecumActo[]): EleccionVademecum | null {
  const buscado = normalizar(texto)
  if (!buscado) return null
  if (buscado === normalizar(SIN_EFECTO)) return { tipo: 'sin_efecto' }
  if (buscado === normalizar(FUERA)) return { tipo: 'fuera' }
  const acto = actos.find(
    (a) =>
      normalizar(a.nombre) === buscado ||
      (a.sinonimos ?? '').split(',').some((s) => normalizar(s) === buscado),
  )
  return acto ? { tipo: 'vademecum', acto } : null
}

/** La planilla no tiene columna de naturaleza: si quedó vacía (un renglón que heredó el acto
 * del anterior), se completa con el nombre del acto del vademécum. */
function conNaturaleza(form: ActoForm, actos: VademecumActo[]): ActoForm {
  if (form.naturaleza.trim()) return form
  const acto = actos.find((a) => a.id === form.vademecum_id)
  return acto ? { ...form, naturaleza: acto.nombre } : form
}

/** Por qué un renglón todavía no se puede guardar (null si está completo). */
function faltante(form: ActoForm, conVademecum: boolean): string | null {
  if (actoCompleto(form, conVademecum)) return null
  if (conVademecum && !form.vademecum_id && !form.fuera_de_vademecum) {
    return form.categoria === 'SIN_EFECTO' ? null : 'Elegí el acto del vademécum.'
  }
  if (!/^\d+$/.test(form.numero_escritura)) return 'Falta el número de escritura.'
  if (!form.fecha_acto) return 'Falta la fecha.'
  if (form.naturaleza.trim().length < 3) return 'Falta la naturaleza del acto: abrí «Más».'
  if (form.categoria === 'ESCRITURA_CON_VALOR') {
    return conVademecum ? 'Falta el precio o el avalúo.' : 'Falta la base imponible.'
  }
  return 'Falta completar el acto: abrí «Más».'
}

function EstadoRenglon({
  guardando,
  error,
  falta,
}: {
  guardando: boolean
  error: boolean
  falta: string | null
}) {
  const [Icono, clase, texto] = guardando
    ? [LoaderCircle, 'animate-spin text-ink-muted', 'Guardando']
    : error
      ? [CircleX, 'text-danger-700', 'No se guardó']
      : falta
        ? [CircleDashed, 'text-ink-muted', 'Incompleto']
        : [CircleCheck, 'text-success-700', 'Listo para guardar']
  return (
    <span className="flex min-h-11 items-center" title={texto}>
      <Icono aria-hidden="true" className={`size-5 ${clase}`} strokeWidth={2.25} />
      <span className="sr-only">{texto}</span>
    </span>
  )
}

/** Aporte estimado y avisos del libro de protocolo de un renglón, como en el alta de a uno:
 * el servidor lo calcula con los parámetros del período tras una breve pausa al tipear. */
function AporteRenglon({
  ddjjId,
  form,
  clave,
  onBloqueo,
}: {
  ddjjId: string
  form: ActoForm
  clave: number
  onBloqueo: (clave: number, bloqueado: boolean) => void
}) {
  const { verificacion, bloqueado, actualizando } = useVerificacionActo(ddjjId, form)
  useEffect(() => {
    onBloqueo(clave, bloqueado)
  }, [clave, bloqueado, onBloqueo])
  if (!verificacion) return null
  const { aporte, controles } = verificacion
  if (aporte === null && controles.length === 0) return null
  return (
    <div
      className="mt-2 flex flex-col gap-1 text-sm sm:flex-row sm:items-start sm:justify-between sm:gap-4 sm:pl-8"
      aria-live="polite"
      aria-busy={actualizando}
    >
      <ul className="grid gap-1">
        {controles.map((c) => {
          const bloquea = c.nivel === 'BLOQUEANTE'
          const Icono = bloquea ? CircleX : TriangleAlert
          return (
            <li
              key={c.codigo}
              className={`flex items-start gap-1.5 ${bloquea ? 'text-danger-700' : 'text-warning-700'}`}
            >
              <Icono aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={2.25} />
              {c.mensaje}
            </li>
          )
        })}
      </ul>
      {aporte !== null && (
        <p className="flex shrink-0 items-baseline gap-2 sm:justify-end">
          <span className="text-ink-muted">Aporte estimado</span>
          <span
            className={`font-semibold text-ink tabular-nums transition-opacity duration-150 ${actualizando ? 'opacity-60' : ''}`}
          >
            {formatMoney(aporte)}
          </span>
        </p>
      )}
    </div>
  )
}

/** Número o folio repetido entre los renglones que todavía no se guardaron: el libro de
 * protocolo no admite dos escrituras con el mismo número ni dos escrituras en el mismo folio
 * (solo los actos de una misma escritura lo comparten). */
function repetidoEnPlanilla(renglones: Renglon[], indice: number): string | null {
  const actual = renglones[indice]
  if (!actual) return null
  const { form } = actual
  for (let j = 0; j < indice; j += 1) {
    const otro = renglones[j]?.form
    if (!otro || otro.tipo_protocolo !== form.tipo_protocolo) continue
    const mismaEscritura =
      form.numero_escritura.trim() !== '' &&
      otro.numero_escritura.trim() === form.numero_escritura.trim()
    if (mismaEscritura && !form.acto_multiple) {
      return `La escritura N° ${form.numero_escritura} ya está en el renglón ${String(j + 1)}: si es otro acto de la misma escritura, marcalo en «Más».`
    }
    if (!mismaEscritura && form.folio.trim() !== '' && otro.folio.trim() === form.folio.trim()) {
      return `El folio ${form.folio} ya está en el renglón ${String(j + 1)}: corregí el folio.`
    }
  }
  return null
}

/** Etiqueta visible solo en celular, donde no hay cabecera de columnas. */
function Etiqueta({ htmlFor, children }: { htmlFor: string; children: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-sm font-medium text-ink sm:sr-only">
      {children}
    </label>
  )
}

/** Carga de actos de la DDJJ renglón por renglón, como en la planilla de la Caja. Cada renglón
 * completo se guarda en orden con el mismo control del libro que la carga de a uno. */
export function CargaPlanilla({
  ddjj,
  onCerrar,
}: {
  ddjj: DeclaracionDetalle
  /** Cerrar la planilla (sin renglones pendientes no hace falta confirmar). */
  onCerrar?: () => void
}) {
  const queryClient = useQueryClient()
  const { actos: vademecum } = useVademecumDelPeriodo(ddjj.periodo)
  const conVademecum = vademecum.length > 0
  const idBase = useId()
  const listaActos = `${idBase}-actos`
  const { desde, hasta } = rangoPeriodo(ddjj.periodo)
  const hoy = todayIso()
  const proximaClave = useRef(1)
  const nuevo = (form: ActoForm): Renglon => ({
    clave: proximaClave.current++,
    form,
    consulta: '',
    abierto: false,
    error: null,
  })
  const [renglones, setRenglones] = useState<Renglon[]>(() => [nuevo(actoSugerido(ddjj, hoy))])
  const [escribanoLote, setEscribanoLote] = useState(() => renglones[0]?.form.escribano_id ?? '')
  const [guardando, setGuardando] = useState<number | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  // Renglones con un aviso del libro que impide guardar (p. ej. número repetido).
  const [bloqueados, setBloqueados] = useState<ReadonlySet<number>>(() => new Set())
  const marcarBloqueo = useCallback((clave: number, bloqueado: boolean) => {
    setBloqueados((actual) => {
      if (actual.has(clave) === bloqueado) return actual
      const nuevo = new Set(actual)
      if (bloqueado) nuevo.add(clave)
      else nuevo.delete(clave)
      return nuevo
    })
  }, [])

  const id = (clave: number, columna: Columna) => `${idBase}-${String(clave)}-${columna}`
  const enfocar = (clave: number, columna: Columna) => {
    requestAnimationFrame(() => {
      document.getElementById(id(clave, columna))?.focus()
    })
  }
  const cambiar = (clave: number, cambio: Partial<Renglon>) => {
    setRenglones((rs) => rs.map((r) => (r.clave === clave ? { ...r, ...cambio, error: null } : r)))
  }
  const cambiarForm = (clave: number, cambio: Partial<ActoForm>) => {
    setRenglones((rs) =>
      rs.map((r) =>
        r.clave === clave ? { ...r, form: { ...r.form, ...cambio }, error: null } : r,
      ),
    )
  }
  const agregarRenglon = (enfocarEn: Columna = 'numero') => {
    const ultimo = renglones.at(-1)
    const renglon = nuevo(
      ultimo
        ? actoSiguiente(ultimo.form, ddjj)
        : { ...actoSugerido(ddjj, hoy), escribano_id: escribanoLote },
    )
    setRenglones((rs) => [...rs, renglon])
    enfocar(renglon.clave, enfocarEn)
  }
  const quitar = (clave: number) => {
    setRenglones((rs) => rs.filter((r) => r.clave !== clave))
  }
  const elegirEscribano = (escribano: string) => {
    // Cambia los renglones que tenían el del lote; los que se cambiaron uno por uno, no.
    setRenglones((rs) =>
      rs.map((r) =>
        r.form.escribano_id === escribanoLote
          ? { ...r, form: { ...r.form, escribano_id: escribano } }
          : r,
      ),
    )
    setEscribanoLote(escribano)
  }

  /** Enter pasa a la celda siguiente; en la última celda del último renglón, agrega otro. */
  const alTeclear = (e: KeyboardEvent<HTMLElement>, clave: number, columna: Columna) => {
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return
    e.preventDefault()
    const indice = renglones.findIndex((r) => r.clave === clave)
    const renglon = renglones[indice]
    const habilitadas = COLUMNAS.filter((c) => {
      if (!renglon) return false
      const conValor = renglon.form.categoria === 'ESCRITURA_CON_VALOR'
      if (c === 'precio' || c === 'avaluo') return conValor && conVademecum
      if (c === 'base') return conValor && !conVademecum
      return c !== 'tipo' || eligeTipo(renglon.form, conVademecum)
    })
    const siguiente = habilitadas[habilitadas.indexOf(columna) + 1]
    if (siguiente) {
      enfocar(clave, siguiente)
      return
    }
    const proximo = renglones[indice + 1]
    if (proximo) enfocar(proximo.clave, 'numero')
    else agregarRenglon()
  }

  const elegirActo = (renglon: Renglon, texto: string) => {
    if (!conVademecum) {
      cambiarForm(renglon.clave, { naturaleza: texto })
      return
    }
    const eleccion = eleccionPorTexto(texto, vademecum)
    if (eleccion) {
      setRenglones((rs) =>
        rs.map((r) =>
          r.clave === renglon.clave
            ? {
                ...r,
                consulta: '',
                // «No está en el vademécum» necesita la naturaleza y la categoría: se abre el
                // editor completo.
                abierto: r.abierto || eleccion.tipo === 'fuera',
                form: { ...r.form, ...alElegir(eleccion, r.form, vademecum) },
                error: null,
              }
            : r,
        ),
      )
      return
    }
    setRenglones((rs) =>
      rs.map((r) =>
        r.clave === renglon.clave
          ? {
              ...r,
              consulta: texto,
              form: { ...r.form, vademecum_id: '', fuera_de_vademecum: false },
              error: null,
            }
          : r,
      ),
    )
  }

  const completos = renglones.filter(
    (r, i) =>
      faltante(conNaturaleza(r.form, vademecum), conVademecum) === null &&
      !bloqueados.has(r.clave) &&
      repetidoEnPlanilla(renglones, i) === null,
  )
  const pendientes = renglones.length

  /** Guarda los renglones completos de a uno y en orden: cada acto pasa por el control del
   * libro con los anteriores ya cargados. Ante un error se detiene en ese renglón. */
  const guardar = async () => {
    setAviso(null)
    let guardados = 0
    for (const renglon of completos) {
      setGuardando(renglon.clave)
      try {
        await agregarActo(ddjj.id, actoInput(conNaturaleza(renglon.form, vademecum)))
        guardados += 1
        setRenglones((rs) => rs.filter((r) => r.clave !== renglon.clave))
      } catch (error) {
        setRenglones((rs) =>
          rs.map((r) =>
            r.clave === renglon.clave ? { ...r, error: toProblem(error), abierto: true } : r,
          ),
        )
        break
      }
    }
    setGuardando(null)
    await queryClient.invalidateQueries({ queryKey: ['ddjj', 'declaracion', ddjj.id] })
    await queryClient.invalidateQueries({ queryKey: ['ddjj', 'declaraciones'] })
    if (guardados > 0) {
      setAviso(guardados === 1 ? 'Se guardó 1 acto.' : `Se guardaron ${String(guardados)} actos.`)
    }
    // Siempre queda un renglón listo para seguir, con el número que sigue.
    setRenglones((rs) => {
      if (rs.length > 0) return rs
      const base = { ...actoSugerido(ddjj, hoy), escribano_id: escribanoLote }
      const ultimo = completos.at(guardados - 1)
      return [nuevo(ultimo ? actoSiguiente(ultimo.form, ddjj) : base)]
    })
  }

  const ocupado = guardando !== null
  const grilla = conVademecum ? GRILLA_VADEMECUM : GRILLA_BASE

  return (
    <section aria-label="Carga en planilla" className="border-b border-line">
      {/* Sin vademécum, la naturaleza se escribe libre: una lista sugeriría un tipo de aporte
          que la naturaleza no fija. */}
      {conVademecum && (
        <datalist id={listaActos}>
          {[...vademecum.map((a) => a.nombre), SIN_EFECTO, FUERA].map((n) => (
            <option key={n} value={n} />
          ))}
        </datalist>
      )}

      <div className="flex flex-col gap-3 px-5 pt-5 sm:flex-row sm:items-end sm:justify-between sm:px-6">
        <p className="max-w-prose text-sm text-ink-muted">
          Un renglón por acto. Enter pasa a la celda siguiente y, al final, abre otro renglón. Para
          un exento u otro acto de la misma escritura, abrí la flecha del renglón.
        </p>
        {ddjj.escribanos.length > 1 && (
          <Select
            label="Escribano autorizante del acto que se está cargando"
            className="sm:w-96 sm:shrink-0"
            value={escribanoLote}
            onChange={(e) => {
              elegirEscribano(e.target.value)
            }}
            options={ddjj.escribanos.map((e) => ({
              value: e.id,
              label: `${e.apellido_nombre} · ${CARGO[e.cargo]} · Mat. ${matriculaTexto(e.matricula_numero)}`,
            }))}
          />
        )}
      </div>

      <div className="px-5 py-4 sm:px-6">
        <div
          aria-hidden="true"
          className={`hidden border-b border-line pb-2 text-xs font-semibold text-ink-muted ${grilla}`}
        >
          <span />
          <span>Protocolo</span>
          <span>N° escr.</span>
          <span>Folio</span>
          <span>Fecha</span>
          <span>Acto</span>
          <span>Tipo</span>
          {conVademecum ? (
            <>
              <span className="text-right">Precio</span>
              <span className="text-right">Avalúo</span>
            </>
          ) : (
            <span className="text-right">Base imponible</span>
          )}
          <span />
        </div>

        <ol className="divide-y divide-line">
          {renglones.map((renglon, i) => {
            const { form } = renglon
            const conValor = form.categoria === 'ESCRITURA_CON_VALOR'
            const repetido = repetidoEnPlanilla(renglones, i)
            const falta =
              repetido ??
              faltante(conNaturaleza(form, vademecum), conVademecum) ??
              (bloqueados.has(renglon.clave) ? 'Revisá el aviso del protocolo.' : null)
            const textoActo = conVademecum
              ? renglon.consulta || textoDeEleccion(eleccionDe(form, vademecum))
              : form.naturaleza
            const n = String(i + 1)
            const otroEscribano =
              ddjj.escribanos.length > 1 && form.escribano_id !== escribanoLote
                ? ddjj.escribanos.find((e) => e.id === form.escribano_id)
                : undefined
            const enCurso = guardando === renglon.clave
            const celda = (columna: Columna) => ({
              id: id(renglon.clave, columna),
              disabled: ocupado,
              onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
                alTeclear(e, renglon.clave, columna)
              },
            })
            return (
              <li key={renglon.clave} className="py-3">
                <div
                  className={`grid grid-cols-2 gap-x-3 gap-y-3 ${grilla}`}
                  aria-label={`Renglón ${n}`}
                  role="group"
                >
                  <div className="col-span-2 flex items-center gap-2 sm:col-span-1 sm:block">
                    <EstadoRenglon
                      guardando={enCurso}
                      error={renglon.error !== null}
                      falta={falta}
                    />
                    <span className="text-sm font-semibold text-ink sm:hidden">Renglón {n}</span>
                  </div>
                  <div>
                    <Etiqueta htmlFor={id(renglon.clave, 'protocolo')}>Protocolo</Etiqueta>
                    <div className="relative">
                      <select
                        {...celda('protocolo')}
                        value={form.tipo_protocolo}
                        onChange={(e) => {
                          const tipo = e.target.value as ActoForm['tipo_protocolo']
                          cambiarForm(renglon.clave, {
                            tipo_protocolo: tipo,
                            numero_escritura: String(ddjj.proximos_numeros[tipo]),
                          })
                        }}
                        aria-label={`Protocolo, renglón ${n}`}
                        className={`${CELDA} cursor-pointer appearance-none border-line-strong pr-7`}
                      >
                        {(['GENERAL', 'AUXILIAR'] as const).map((t) => (
                          <option key={t} value={t}>
                            {PROTOCOLO_CORTO[t]}
                          </option>
                        ))}
                      </select>
                      <ChevronDown
                        aria-hidden="true"
                        className="pointer-events-none absolute top-1/2 right-2 size-4 -translate-y-1/2 text-ink-muted"
                        strokeWidth={2.25}
                      />
                    </div>
                  </div>
                  <div>
                    <Etiqueta htmlFor={id(renglon.clave, 'numero')}>N° de escritura</Etiqueta>
                    <input
                      {...celda('numero')}
                      inputMode="numeric"
                      autoComplete="off"
                      value={form.numero_escritura}
                      onChange={(e) => {
                        cambiarForm(renglon.clave, { numero_escritura: e.target.value })
                      }}
                      aria-label={`N° de escritura, renglón ${n}`}
                      className={`${CELDA} border-line-strong`}
                    />
                  </div>
                  <div>
                    <Etiqueta htmlFor={id(renglon.clave, 'folio')}>Folio</Etiqueta>
                    <input
                      {...celda('folio')}
                      inputMode="numeric"
                      autoComplete="off"
                      placeholder="—"
                      value={form.folio}
                      onChange={(e) => {
                        cambiarForm(renglon.clave, { folio: e.target.value })
                      }}
                      aria-label={`Folio, renglón ${n}`}
                      className={`${CELDA} border-line-strong`}
                    />
                  </div>
                  <div className="col-span-2 sm:col-span-1">
                    <Etiqueta htmlFor={id(renglon.clave, 'fecha')}>Fecha</Etiqueta>
                    <input
                      {...celda('fecha')}
                      type="date"
                      min={desde}
                      max={hasta < hoy ? hasta : hoy}
                      value={form.fecha_acto}
                      onChange={(e) => {
                        cambiarForm(renglon.clave, { fecha_acto: e.target.value })
                      }}
                      aria-label={`Fecha del acto, renglón ${n}`}
                      className={`${CELDA} border-line-strong`}
                    />
                  </div>
                  <div className="col-span-2 sm:col-span-1">
                    <Etiqueta htmlFor={id(renglon.clave, 'acto')}>Acto</Etiqueta>
                    <input
                      {...celda('acto')}
                      list={conVademecum ? listaActos : undefined}
                      autoComplete="off"
                      placeholder={conVademecum ? 'Buscá en el vademécum' : 'Naturaleza del acto'}
                      value={textoActo}
                      onChange={(e) => {
                        elegirActo(renglon, e.target.value)
                      }}
                      aria-label={`Acto, renglón ${n}`}
                      className={`${CELDA} ${renglon.consulta ? 'border-warning-700' : 'border-line-strong'}`}
                    />
                  </div>
                  <div className="col-span-2 sm:col-span-1">
                    <Etiqueta htmlFor={id(renglon.clave, 'tipo')}>Tipo</Etiqueta>
                    <div className="relative">
                      <select
                        {...celda('tipo')}
                        disabled={ocupado || !eligeTipo(form, conVademecum)}
                        value={form.categoria}
                        onChange={(e) => {
                          const categoria = e.target.value as CategoriaActo
                          setRenglones((rs) =>
                            rs.map((r) =>
                              r.clave === renglon.clave
                                ? {
                                    ...r,
                                    form: {
                                      ...r.form,
                                      categoria,
                                      ...(categoria === 'SIN_EFECTO' &&
                                        !r.form.naturaleza.trim() && {
                                          naturaleza: SIN_EFECTO,
                                        }),
                                    },
                                    error: null,
                                  }
                                : r,
                            ),
                          )
                        }}
                        aria-label={`Tipo de aporte, renglón ${n}`}
                        title={
                          eligeTipo(form, conVademecum)
                            ? undefined
                            : 'Lo fija el acto elegido del vademécum'
                        }
                        className={`${CELDA} cursor-pointer appearance-none border-line-strong pr-7`}
                      >
                        {TIPOS.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                      <ChevronDown
                        aria-hidden="true"
                        className="pointer-events-none absolute top-1/2 right-2 size-4 -translate-y-1/2 text-ink-muted"
                        strokeWidth={2.25}
                      />
                    </div>
                  </div>
                  {conVademecum ? (
                    <>
                      <div>
                        <Etiqueta htmlFor={id(renglon.clave, 'precio')}>Precio</Etiqueta>
                        <input
                          {...celda('precio')}
                          disabled={ocupado || !conValor}
                          inputMode="decimal"
                          autoComplete="off"
                          placeholder={conValor ? '0,00' : '—'}
                          value={conValor ? form.precio : ''}
                          onChange={(e) => {
                            cambiarForm(renglon.clave, { precio: e.target.value })
                          }}
                          aria-label={`Precio, renglón ${n}`}
                          className={`${CELDA} border-line-strong text-right`}
                        />
                      </div>
                      <div>
                        <Etiqueta htmlFor={id(renglon.clave, 'avaluo')}>Avalúo</Etiqueta>
                        <input
                          {...celda('avaluo')}
                          disabled={ocupado || !conValor}
                          inputMode="decimal"
                          autoComplete="off"
                          placeholder={conValor ? '0,00' : '—'}
                          value={conValor ? form.avaluo : ''}
                          onChange={(e) => {
                            cambiarForm(renglon.clave, { avaluo: e.target.value })
                          }}
                          aria-label={`Avalúo, renglón ${n}`}
                          className={`${CELDA} border-line-strong text-right`}
                        />
                      </div>
                    </>
                  ) : (
                    <div className="col-span-2 sm:col-span-1">
                      <Etiqueta htmlFor={id(renglon.clave, 'base')}>Base imponible</Etiqueta>
                      <input
                        {...celda('base')}
                        disabled={ocupado || !conValor}
                        inputMode="decimal"
                        autoComplete="off"
                        placeholder={conValor ? '0,00' : '—'}
                        value={conValor ? form.base_imponible : ''}
                        onChange={(e) => {
                          cambiarForm(renglon.clave, { base_imponible: e.target.value })
                        }}
                        aria-label={`Base imponible, renglón ${n}`}
                        className={`${CELDA} border-line-strong text-right`}
                      />
                    </div>
                  )}
                  <div className="col-span-2 flex gap-1 sm:col-span-1">
                    <button
                      type="button"
                      disabled={ocupado}
                      aria-expanded={renglon.abierto}
                      aria-label={`Más datos del renglón ${n}`}
                      aria-controls={`${idBase}-${String(renglon.clave)}-editor`}
                      onClick={() => {
                        cambiar(renglon.clave, { abierto: !renglon.abierto })
                      }}
                      className="inline-flex min-h-11 flex-1 cursor-pointer items-center justify-center gap-1 rounded-control px-2 text-sm font-semibold text-brand-800 transition-colors duration-150 ease-out-quint hover:bg-brand-50 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <span className="sm:sr-only">Más</span>
                      <ChevronDown
                        aria-hidden="true"
                        className={`size-4 transition-transform duration-150 ${renglon.abierto ? 'rotate-180' : ''}`}
                        strokeWidth={2.25}
                      />
                    </button>
                    <button
                      type="button"
                      disabled={ocupado || renglones.length === 1}
                      onClick={() => {
                        quitar(renglon.clave)
                      }}
                      aria-label={`Quitar el renglón ${n}`}
                      className="inline-flex min-h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-control text-ink-muted transition-colors duration-150 ease-out-quint hover:bg-danger-50 hover:text-danger-700 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <Trash2 aria-hidden="true" className="size-4" strokeWidth={2.25} />
                    </button>
                  </div>
                </div>

                <AporteRenglon
                  ddjjId={ddjj.id}
                  form={conNaturaleza(form, vademecum)}
                  clave={renglon.clave}
                  onBloqueo={marcarBloqueo}
                />

                {(renglon.error ??
                  (renglon.consulta ||
                    otroEscribano ||
                    repetido ||
                    (falta && i < pendientes - 1))) && (
                  <div className="mt-2 grid gap-1 text-sm sm:pl-8">
                    {renglon.error && (
                      <p className="flex items-start gap-1.5 text-danger-700" role="alert">
                        <CircleX
                          aria-hidden="true"
                          className="mt-0.5 size-4 shrink-0"
                          strokeWidth={2.25}
                        />
                        {renglon.error.detail}
                      </p>
                    )}
                    {!renglon.error && renglon.consulta && (
                      <p className="text-warning-700">
                        «{renglon.consulta}» no está en el vademécum: elegí uno de la lista o «
                        {FUERA}».
                      </p>
                    )}
                    {!renglon.error && repetido && (
                      <p className="flex items-start gap-1.5 text-danger-700" role="alert">
                        <CircleX
                          aria-hidden="true"
                          className="mt-0.5 size-4 shrink-0"
                          strokeWidth={2.25}
                        />
                        {repetido}
                      </p>
                    )}
                    {!renglon.error &&
                      !renglon.consulta &&
                      !repetido &&
                      falta &&
                      i < pendientes - 1 && <p className="text-ink-muted">{falta}</p>}
                    {otroEscribano && (
                      <p className="text-ink-muted">Escribano: {otroEscribano.apellido_nombre}.</p>
                    )}
                  </div>
                )}

                {renglon.abierto && (
                  <div
                    id={`${idBase}-${String(renglon.clave)}-editor`}
                    className="mt-3 rounded-control border border-line bg-surface-sunken p-4 sm:ml-8"
                  >
                    <ActoCampos
                      ddjj={ddjj}
                      form={form}
                      problem={renglon.error}
                      onChange={(cambio) => {
                        setRenglones((rs) =>
                          rs.map((r) =>
                            r.clave === renglon.clave
                              ? { ...r, consulta: '', form: { ...r.form, ...cambio }, error: null }
                              : r,
                          ),
                        )
                      }}
                    />
                  </div>
                )}
              </li>
            )
          })}
        </ol>
      </div>

      <div className="flex flex-col gap-3 border-t border-line bg-surface-sunken px-5 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div aria-live="polite" className="text-sm text-ink-muted">
          {aviso ? (
            <span className="font-semibold text-success-700">{aviso}</span>
          ) : (
            `${String(completos.length)} de ${String(pendientes)} ${pendientes === 1 ? 'renglón listo' : 'renglones listos'} para guardar`
          )}
        </div>
        <div className="flex flex-col-reverse gap-3 sm:flex-row">
          {onCerrar && (
            <Button variant="ghost" disabled={ocupado} onClick={onCerrar}>
              Cerrar la planilla
            </Button>
          )}
          <Button
            icon={Plus}
            disabled={ocupado}
            onClick={() => {
              agregarRenglon()
            }}
          >
            Agregar renglón
          </Button>
          <Button
            variant="primary"
            icon={Save}
            busy={ocupado}
            busyLabel="Guardando…"
            disabled={completos.length === 0}
            onClick={() => {
              void guardar()
            }}
          >
            {completos.length > 1 ? `Guardar ${String(completos.length)} actos` : 'Guardar'}
          </Button>
        </div>
      </div>
      {renglones.some((r) => r.error) && (
        <div className="px-5 pb-4 sm:px-6">
          <Alert tone="danger">
            Los renglones anteriores al marcado se guardaron. Corregí ese renglón y volvé a guardar
            para seguir.
          </Alert>
        </div>
      )}
    </section>
  )
}
