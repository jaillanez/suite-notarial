import { CircleX, Plus, Trash2, TriangleAlert } from 'lucide-react'
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

import { Button } from '../../components/ui/Button'
import { formatMoney } from '../../lib/decimal'
import { CARGO } from '../padron/labels'
import type {
  Acto,
  ControlProtocolo,
  DeclaracionDetalle,
  Planilla,
  ProtocoloPlanilla,
  RenglonPlanilla,
  TipoProtocolo,
} from './api'
import { PROTOCOLO, categoriaDe } from './labels'

type Pestania = TipoProtocolo | 'RESUMEN'

const TITULO: Record<Pestania, string> = {
  GENERAL: 'Protocolo General',
  AUXILIAR: 'Protocolo Auxiliar',
  RESUMEN: 'Resumen',
}

/** En el celular, las pestañas sin «Protocolo» para que entren las tres. */
const CORTO: Record<TipoProtocolo, string> = { GENERAL: 'General', AUXILIAR: 'Auxiliar' }

/** Importe o vacío, como la planilla (una celda sin aporte queda en blanco). */
function importe(valor: string | null): string {
  return valor === null ? '' : formatMoney(valor)
}

function numeroRenglon(r: RenglonPlanilla): string {
  return r.orden_en_escritura > 1
    ? `${String(r.numero_escritura)} · acto ${String(r.orden_en_escritura)}`
    : String(r.numero_escritura)
}

function rango(desde: number | null, hasta: number | null, prefijo = ''): string {
  if (desde === null || hasta === null) return '—'
  return desde === hasta
    ? `${prefijo}${String(desde)}`
    : `del ${prefijo}${String(desde)} al ${prefijo}${String(hasta)}`
}

/** Avisos del libro de protocolo bajo un renglón (ícono y texto en el tono del aviso). */
function Controles({ controles }: { controles: ControlProtocolo[] | undefined }) {
  if (!controles?.length) return null
  return (
    <ul className="mt-1.5 grid gap-1">
      {controles.map((c) => {
        const bloqueante = c.nivel === 'BLOQUEANTE'
        const Icono = bloqueante ? CircleX : TriangleAlert
        return (
          <li
            key={c.codigo}
            className={`flex gap-1.5 text-sm font-medium ${bloqueante ? 'text-danger-700' : 'text-warning-700'}`}
          >
            <Icono aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={2.25} />
            <span>{c.mensaje}</span>
          </li>
        )
      })}
    </ul>
  )
}

function FueraDeVademecum() {
  return (
    <span className="mt-1 flex gap-1.5 text-sm font-medium text-warning-700">
      <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={2.25} />
      No está en el vademécum: lo revisa la Caja
    </span>
  )
}

/** Celda de aporte en la columna de un cargo: lo que se paga y, si quedó incluido, la nota. */
function CeldaCargo({ r, cargo }: { r: RenglonPlanilla; cargo: RenglonPlanilla['cargo'] }) {
  if (r.cargo !== cargo || r.aporte === null) return null
  return (
    <>
      <span className="block">{formatMoney(r.aporte)}</span>
      {r.incluido_en_otro && (
        <span className="block text-xs font-normal whitespace-nowrap text-ink-muted">
          Incluido en el principal
        </span>
      )}
    </>
  )
}

const TH = 'px-2 py-2.5 text-xs font-semibold text-ink-muted'
const TD = 'px-2 py-3 align-top'
const NUM = 'text-right whitespace-nowrap tabular-nums'

function ProtocoloGrilla({
  protocolo,
  ddjj,
  conACargo,
  editable,
  onQuitar,
}: {
  protocolo: ProtocoloPlanilla
  ddjj: DeclaracionDetalle
  conACargo: boolean
  editable: boolean
  onQuitar: (acto: Acto) => void
}) {
  const actos = new Map(ddjj.actos.map((a) => [a.id, a]))
  const cargos = conACargo
    ? (['TITULAR', 'ADSCRIPTO', 'SUPLENTE_INTERINO'] as const)
    : (['TITULAR', 'ADSCRIPTO'] as const)
  const { renglones, totales } = protocolo
  if (renglones.length === 0) {
    return (
      <p className="px-5 py-8 text-center text-ink-muted sm:px-6">
        Sin escrituras en el {PROTOCOLO[protocolo.tipo].toLowerCase()} este mes.
      </p>
    )
  }
  const quitar = (r: RenglonPlanilla): ReactNode => {
    const acto = r.acto_id ? actos.get(r.acto_id) : undefined
    if (!editable || !acto) return null
    return (
      <Button
        variant="ghost"
        icon={Trash2}
        aria-label={`Quitar el acto ${numeroRenglon(r)}`}
        onClick={() => {
          onQuitar(acto)
        }}
      >
        <span className="lg:sr-only">Quitar</span>
      </Button>
    )
  }
  const detalle = (r: RenglonPlanilla) => {
    const acto = r.acto_id ? actos.get(r.acto_id) : undefined
    return (
      <>
        {acto?.fuera_de_vademecum && <FueraDeVademecum />}
        <Controles controles={r.acto_id ? ddjj.controles[r.acto_id] : undefined} />
      </>
    )
  }

  return (
    <>
      <div className="hidden lg:block">
        <table className="w-full text-sm">
          <thead className="bg-surface-sunken">
            <tr>
              <th scope="col" className={`${TH} pl-6 text-left`}>
                Escritura
              </th>
              <th scope="col" className={`${TH} min-w-56 text-left`}>
                Naturaleza del acto
              </th>
              <th scope="col" className={`${TH} text-right`}>
                Base imponible
              </th>
              <th scope="col" className={`${TH} text-right`}>
                Aporte
              </th>
              <th scope="col" className={`${TH} text-right`}>
                Aporte fijo
              </th>
              {cargos.map((c) => (
                <th key={c} scope="col" className={`${TH} text-right`}>
                  {CARGO[c]}
                </th>
              ))}
              {editable && (
                <th scope="col" className="w-0 pr-4">
                  <span className="sr-only">Acciones</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {renglones.map((r) => (
              <tr key={r.acto_id ?? numeroRenglon(r)}>
                <td className={`${TD} pl-6 whitespace-nowrap tabular-nums`}>
                  <span className="block font-semibold text-ink">N° {numeroRenglon(r)}</span>
                  {r.folio !== null && (
                    <span className="block text-ink-muted">Folio {r.folio}</span>
                  )}
                </td>
                <td className={TD}>
                  <span className="block text-ink">{r.naturaleza}</span>
                  <span className="block text-ink-muted">
                    {categoriaDe({ ...r, motivo_exencion: null, detalle_exencion: null })} ·{' '}
                    {CARGO[r.cargo]}: {r.escribano}
                  </span>
                  {detalle(r)}
                </td>
                <td className={`${TD} ${NUM} text-ink`}>{importe(r.base_imponible)}</td>
                <td className={`${TD} ${NUM} text-ink`}>{importe(r.aporte_variable)}</td>
                <td className={`${TD} ${NUM} text-ink`}>{importe(r.aporte_fijo)}</td>
                {cargos.map((c) => (
                  <td key={c} className={`${TD} ${NUM} font-semibold text-ink`}>
                    <CeldaCargo r={r} cargo={c} />
                  </td>
                ))}
                {editable && <td className="py-1.5 pr-4 align-top">{quitar(r)}</td>}
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t-2 border-brand-900 bg-surface-sunken font-semibold text-ink">
            <tr>
              <th scope="row" colSpan={3} className={`${TD} pl-6 text-left`}>
                Totales
              </th>
              <td className={`${TD} ${NUM}`}>{formatMoney(totales.aporte_variable)}</td>
              <td className={`${TD} ${NUM}`}>{formatMoney(totales.aporte_fijo)}</td>
              <td className={`${TD} ${NUM}`}>{formatMoney(totales.titular)}</td>
              <td className={`${TD} ${NUM}`}>{formatMoney(totales.adscripto)}</td>
              {conACargo && <td className={`${TD} ${NUM}`}>{formatMoney(totales.a_cargo)}</td>}
              {editable && <td />}
            </tr>
          </tfoot>
        </table>
      </div>
      <ul className="divide-y divide-line lg:hidden">
        {renglones.map((r) => (
          <li key={r.acto_id ?? numeroRenglon(r)} className="px-5 py-4 sm:px-6">
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-semibold text-ink tabular-nums">
                N° {numeroRenglon(r)}
                {r.folio !== null && (
                  <span className="font-normal text-ink-muted"> · Folio {r.folio}</span>
                )}
              </span>
              <span className="text-right font-semibold text-ink tabular-nums">
                {importe(r.aporte)}
                {r.incluido_en_otro && (
                  <span className="block text-xs font-normal text-ink-muted">
                    Incluido en el principal
                  </span>
                )}
              </span>
            </div>
            <p className="mt-1 text-sm text-ink">{r.naturaleza}</p>
            <p className="text-sm text-ink-muted">
              {CARGO[r.cargo]} · {r.escribano}
            </p>
            <p className="text-sm text-ink-muted tabular-nums">
              {r.base_imponible !== null && <>Base {formatMoney(r.base_imponible)} · </>}
              {r.aporte_variable !== null && <>Aporte {formatMoney(r.aporte_variable)}</>}
              {r.aporte_fijo !== null && <>Aporte fijo {formatMoney(r.aporte_fijo)}</>}
              {r.aporte_variable === null && r.aporte_fijo === null && 'Sin aporte'}
            </p>
            {detalle(r)}
            {editable && <div className="-ml-4 mt-1">{quitar(r)}</div>}
          </li>
        ))}
        <li className="flex items-baseline justify-between gap-3 bg-surface-sunken px-5 py-3 font-semibold text-ink sm:px-6">
          <span>Total del protocolo</span>
          <span className="tabular-nums">{formatMoney(totales.total)}</span>
        </li>
      </ul>
    </>
  )
}

function Resumen({ planilla, conACargo }: { planilla: Planilla; conACargo: boolean }) {
  const cargos = conACargo
    ? (['titular', 'adscripto', 'a_cargo'] as const)
    : (['titular', 'adscripto'] as const)
  const titulo = { titular: 'Titular', adscripto: 'Adscripto', a_cargo: 'A cargo' }
  return (
    <div>
      <div className="hidden sm:block">
        <table className="w-full text-sm">
          <thead className="bg-surface-sunken">
            <tr>
              <th scope="col" className={`${TH} pl-6 text-left`}>
                Detalle
              </th>
              <th scope="col" className={`${TH} text-left`}>
                Escrituras
              </th>
              <th scope="col" className={`${TH} text-left`}>
                Folios
              </th>
              {cargos.map((c) => (
                <th key={c} scope="col" className={`${TH} text-right last:pr-6`}>
                  {titulo[c]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {planilla.protocolos.map((p) => (
              <tr key={p.tipo}>
                <th scope="row" className={`${TD} pl-6 text-left font-medium text-ink`}>
                  {TITULO[p.tipo]}
                </th>
                <td className={`${TD} tabular-nums text-ink`}>
                  {rango(p.escrituras_desde, p.escrituras_hasta, 'N° ')}
                </td>
                <td className={`${TD} tabular-nums text-ink`}>
                  {rango(p.folios_desde, p.folios_hasta)}
                </td>
                {cargos.map((c) => (
                  <td key={c} className={`${TD} ${NUM} text-ink last:pr-6`}>
                    {formatMoney(p.totales[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t-2 border-brand-900 bg-surface-sunken font-semibold text-ink">
            <tr>
              <th scope="row" colSpan={3} className={`${TD} pl-6 text-left`}>
                Totales
              </th>
              {cargos.map((c) => (
                <td key={c} className={`${TD} ${NUM} last:pr-6`}>
                  {formatMoney(planilla.totales[c])}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
      <dl className="divide-y divide-line sm:hidden">
        {planilla.protocolos.map((p) => (
          <div key={p.tipo} className="px-5 py-4">
            <dt className="font-semibold text-ink">{TITULO[p.tipo]}</dt>
            <dd className="mt-1 text-sm text-ink-muted tabular-nums">
              Escrituras {rango(p.escrituras_desde, p.escrituras_hasta, 'N° ')} · Folios{' '}
              {rango(p.folios_desde, p.folios_hasta)}
            </dd>
            {cargos.map((c) => (
              <dd key={c} className="flex justify-between text-sm text-ink tabular-nums">
                <span>{titulo[c]}</span>
                <span>{formatMoney(p.totales[c])}</span>
              </dd>
            ))}
          </div>
        ))}
      </dl>
      <div className="flex items-baseline justify-between gap-3 border-t border-line px-5 py-4 sm:px-6">
        <span className="text-sm text-ink-muted">
          Total de protocolos. El aporte mínimo y el médico se liquidan en la boleta de cada
          escribano.
        </span>
        <span className="text-lg font-semibold whitespace-nowrap text-brand-900 tabular-nums">
          {formatMoney(planilla.totales.total)}
        </span>
      </div>
    </div>
  )
}

/**
 * Los actos de la DDJJ con el formato de la planilla de la Caja: una pestaña por protocolo y el
 * resumen. Los importes vienen del servidor (la misma planilla que imprime el PDF).
 */
export function PlanillaActos({
  ddjj,
  planilla,
  editable,
  onAgregar,
  onQuitar,
}: {
  ddjj: DeclaracionDetalle
  planilla: Planilla
  editable: boolean
  onAgregar: (protocolo: TipoProtocolo) => void
  onQuitar: (acto: Acto) => void
}) {
  const id = useId()
  const pestanias: Pestania[] = ['GENERAL', 'AUXILIAR', 'RESUMEN']
  const [activa, setActiva] = useState<Pestania>('GENERAL')
  const botones = useRef<Partial<Record<Pestania, HTMLButtonElement | null>>>({})
  const conACargo =
    planilla.a_cargo.length > 0 ||
    planilla.protocolos.some((p) => p.renglones.some((r) => r.cargo === 'SUPLENTE_INTERINO'))
  const cantidad = (p: Pestania) =>
    p === 'RESUMEN' ? null : (planilla.protocolos.find((x) => x.tipo === p)?.renglones.length ?? 0)

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const i = pestanias.indexOf(activa)
    const destino =
      e.key === 'ArrowRight'
        ? pestanias[(i + 1) % pestanias.length]
        : e.key === 'ArrowLeft'
          ? pestanias[(i - 1 + pestanias.length) % pestanias.length]
          : e.key === 'Home'
            ? pestanias[0]
            : e.key === 'End'
              ? pestanias[pestanias.length - 1]
              : undefined
    if (!destino) return
    e.preventDefault()
    setActiva(destino)
    botones.current[destino]?.focus()
  }
  const protocolo = planilla.protocolos.find((p) => p.tipo === activa)

  return (
    <div>
      <div className="flex min-h-15 flex-wrap items-end justify-between gap-3 border-b border-line px-5 sm:px-6">
        <div role="tablist" aria-label="Hojas de la declaración" className="-mb-px flex gap-1">
          {pestanias.map((p) => {
            const seleccionada = p === activa
            const n = cantidad(p)
            return (
              <button
                key={p}
                ref={(el) => {
                  botones.current[p] = el
                }}
                type="button"
                role="tab"
                id={`${id}-tab-${p}`}
                aria-selected={seleccionada}
                aria-controls={`${id}-panel`}
                tabIndex={seleccionada ? 0 : -1}
                onClick={() => {
                  setActiva(p)
                }}
                onKeyDown={onKeyDown}
                className={`min-h-11 cursor-pointer border-b-2 px-2.5 sm:px-3 text-sm font-semibold whitespace-nowrap transition-colors duration-150 ease-out-quint ${seleccionada ? 'border-brand-800 text-brand-900' : 'border-transparent text-ink-muted hover:text-brand-800'}`}
              >
                {p === 'RESUMEN' ? (
                  TITULO[p]
                ) : (
                  <>
                    <span className="sm:hidden">{CORTO[p]}</span>
                    <span className="hidden sm:inline">{TITULO[p]}</span>
                  </>
                )}
                {n !== null && (
                  <span className="ml-1.5 font-normal text-ink-muted tabular-nums">{n}</span>
                )}
              </button>
            )
          })}
        </div>
        {editable && activa !== 'RESUMEN' && (
          <div className="py-2">
            <Button
              variant="ghost"
              icon={Plus}
              onClick={() => {
                onAgregar(activa)
              }}
            >
              Agregar al {activa === 'GENERAL' ? 'general' : 'auxiliar'}
            </Button>
          </div>
        )}
      </div>
      <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-tab-${activa}`}>
        {protocolo ? (
          <ProtocoloGrilla
            protocolo={protocolo}
            ddjj={ddjj}
            conACargo={conACargo}
            editable={editable}
            onQuitar={onQuitar}
          />
        ) : (
          <Resumen planilla={planilla} conACargo={conACargo} />
        )}
      </div>
    </div>
  )
}
