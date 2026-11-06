import { useMutation, useQuery } from '@tanstack/react-query'
import { FileDown } from 'lucide-react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { formatMoney } from '../../lib/decimal'
import { useSession } from '../auth/session'
import { formatDate } from '../padron/labels'
import { descargarInforme, fetchMisPuntos, fetchPuntosEscribano, type InformePuntos } from './api'
import { formatPuntos } from './labels'

function Tabla({ informe }: { informe: InformePuntos }) {
  const ejercicios = informe.filas.length
  const etiqueta = `Total · ${String(ejercicios)} ${ejercicios === 1 ? 'ejercicio' : 'ejercicios'}`
  return (
    <>
      <div className="hidden max-h-[34rem] overflow-auto sm:block">
        <table className="w-full border-collapse text-sm tabular-nums">
          <caption className="sr-only">Aportes y puntos por ejercicio</caption>
          <thead className="sticky top-0 z-10 bg-surface-sunken text-xs font-semibold text-ink-muted shadow-[inset_0_-1px_0_var(--color-line)]">
            <tr>
              <th scope="col" className="px-3 py-2.5 pl-6 text-left">
                Ejercicio
              </th>
              <th scope="col" className="px-3 py-2.5 text-left">
                Período
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                Aportes
              </th>
              <th scope="col" className="px-3 py-2.5 pr-6 text-right">
                Puntos
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {informe.filas.map((f) => (
              <tr key={f.anio}>
                <th scope="row" className="px-3 py-2 pl-6 text-left font-semibold text-ink">
                  {f.anio}
                </th>
                <td className="px-3 py-2 whitespace-nowrap text-ink-muted">
                  {formatDate(f.fecha_inicio)} al {formatDate(f.fecha_cierre)}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">{formatMoney(f.aportes)}</td>
                <td className="px-3 py-2 pr-6 text-right whitespace-nowrap">
                  {formatPuntos(f.puntos)}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot className="sticky bottom-0 bg-surface-sunken font-semibold text-brand-900 shadow-[inset_0_1px_0_var(--color-line-strong)]">
            <tr>
              <th scope="row" colSpan={2} className="px-3 py-2.5 pl-6 text-left">
                {etiqueta}
              </th>
              <td className="px-3 py-2.5 text-right whitespace-nowrap">
                {formatMoney(informe.total_aportes)}
              </td>
              <td className="px-3 py-2.5 pr-6 text-right whitespace-nowrap">
                {formatPuntos(informe.total_puntos)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <ul className="divide-y divide-line sm:hidden">
        {informe.filas.map((f) => (
          <li key={f.anio} className="px-5 py-3 tabular-nums">
            <div className="flex items-baseline justify-between gap-4">
              <span className="font-semibold text-ink">{f.anio}</span>
              <span className="text-xs text-ink-muted">
                {formatDate(f.fecha_inicio)} al {formatDate(f.fecha_cierre)}
              </span>
            </div>
            <dl className="mt-1 grid grid-cols-2 gap-x-4 text-sm">
              <dt className="text-ink-muted">Aportes</dt>
              <dd className="text-right">{formatMoney(f.aportes)}</dd>
              <dt className="text-ink-muted">Puntos</dt>
              <dd className="text-right">{formatPuntos(f.puntos)}</dd>
            </dl>
          </li>
        ))}
        <li className="bg-surface-sunken px-5 py-3 font-semibold text-brand-900 tabular-nums">
          <p>{etiqueta}</p>
          <dl className="mt-1 grid grid-cols-2 gap-x-4 text-sm">
            <dt>Aportes</dt>
            <dd className="text-right">{formatMoney(informe.total_aportes)}</dd>
            <dt>Puntos</dt>
            <dd className="text-right">{formatPuntos(informe.total_puntos)}</dd>
          </dl>
        </li>
      </ul>
    </>
  )
}

const VINCULO = {
  EXACTA: 'nombre idéntico',
  HEREDADA: 'mismo nombre que un vínculo manual previo, a confirmar',
  MANUAL: 'vinculado a mano',
} as const

/**
 * «Aportes y puntos (Ley 7231)»: tabla por ejercicio, totales y descarga del informe en PDF.
 * Sin `escribanoId` muestra los del escribano que inició sesión.
 */
export function PuntosPanel({
  escribanoId,
  className = '',
}: {
  escribanoId?: string
  className?: string
}) {
  const { user } = useSession()
  const query = useQuery({
    // La clave incluye a quien consulta: «Mis puntos» de una cuenta nunca sirve a otra.
    queryKey: ['previsional', 'puntos', user?.id ?? 'anonimo', escribanoId ?? 'propios'],
    queryFn: () => (escribanoId ? fetchPuntosEscribano(escribanoId) : fetchMisPuntos()),
  })
  const pdf = useMutation({
    mutationFn: () => descargarInforme(escribanoId ? query.data?.escribano : undefined),
  })
  const informe = query.data
  const conDatos = (informe?.filas.length ?? 0) > 0

  return (
    <Panel
      className={className}
      title="Aportes y puntos (Ley 7231)"
      description="Por ejercicio, del 1 de septiembre al 31 de agosto (se nombra por el año de cierre)."
      actions={
        informe && conDatos ? (
          <Button
            icon={FileDown}
            busy={pdf.isPending}
            busyLabel="Generando…"
            onClick={() => {
              pdf.mutate()
            }}
          >
            Informe en PDF
          </Button>
        ) : undefined
      }
      footer={
        escribanoId && informe && informe.origenes.length > 0 ? (
          <span>
            Según la planilla histórica de la Caja:{' '}
            {informe.origenes
              .map((o) => `«${o.nombre_origen}» (${VINCULO[o.vinculacion]})`)
              .join(', ')}
            .
          </span>
        ) : undefined
      }
    >
      <div aria-live="polite" aria-busy={query.isPending}>
        {query.isPending && (
          <div className="space-y-2 px-5 py-5 sm:px-6">
            <span className="block h-5 w-2/3 animate-pulse rounded-control bg-brand-50" />
            <span className="block h-5 w-1/2 animate-pulse rounded-control bg-brand-50" />
          </div>
        )}
        {query.isError && (
          <div className="px-5 py-5 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}
        {pdf.isError && (
          <div className="px-5 pt-5 sm:px-6">
            <Alert tone="danger">{toProblem(pdf.error).detail}</Alert>
          </div>
        )}
        {informe && !conDatos && (
          <p className="px-5 py-6 text-sm text-ink-muted sm:px-6">
            No hay aportes ni puntos registrados.
            {escribanoId
              ? ' Si figura en la planilla histórica con otro nombre, vinculalo desde «Aportes y puntos».'
              : ' Si creés que falta información, consultá con la Caja.'}
          </p>
        )}
        {informe && conDatos && <Tabla informe={informe} />}
      </div>
    </Panel>
  )
}
