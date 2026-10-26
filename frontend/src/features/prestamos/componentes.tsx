import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useDeferredValue, useState } from 'react'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Field } from '../../components/ui/Field'
import { Select } from '../../components/ui/Select'
import { compararDecimal, formatMoney, formatPercent } from '../../lib/decimal'
import { fetchEscribanos } from '../padron/api'
import { formatDate } from '../padron/labels'
import type { Cuota, Evaluacion, Totales } from './api'
import { SISTEMA, estadoCuota } from './labels'

/** Cuadro de amortización: tabla en escritorio, lista apilada en celular, totales al pie. */
export function PlanCuotas({
  plan,
  totales,
  conEstado,
}: {
  plan: Cuota[]
  totales: Totales
  conEstado: boolean
}) {
  const cols = [
    ['N°', 'left'],
    ['Vencimiento', 'left'],
    ['Saldo inicial', 'right'],
    ['Capital', 'right'],
    ['Interés', 'right'],
    ['Cuota', 'right'],
    ['Saldo final', 'right'],
  ] as const
  return (
    <>
      <div className="hidden max-h-[34rem] overflow-auto sm:block">
        <table className="w-full border-collapse text-sm tabular-nums">
          <thead className="sticky top-0 z-10 bg-surface-sunken text-xs font-semibold text-ink-muted shadow-[inset_0_-1px_0_var(--color-line)]">
            <tr>
              {cols.map(([label, align]) => (
                <th
                  key={label}
                  scope="col"
                  className={`px-3 py-2.5 whitespace-nowrap first:pl-6 ${align === 'right' ? 'text-right' : 'text-left'}`}
                >
                  {label}
                </th>
              ))}
              {conEstado && (
                <th scope="col" className="px-3 py-2.5 pr-6 text-left">
                  Estado
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {plan.map((c) => {
              const e = estadoCuota(c)
              return (
                <tr key={c.numero} className={c.vencida ? 'bg-danger-50/50' : undefined}>
                  <td className="px-3 py-2 pl-6 text-ink-muted">{c.numero}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{formatDate(c.vencimiento)}</td>
                  <td className="px-3 py-2 text-right whitespace-nowrap text-ink-muted">
                    {formatMoney(c.saldo_inicial)}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {formatMoney(c.amortizacion)}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {formatMoney(c.interes)}
                  </td>
                  <td className="px-3 py-2 text-right font-semibold whitespace-nowrap">
                    {formatMoney(c.cuota)}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap text-ink-muted">
                    {formatMoney(c.saldo_final)}
                  </td>
                  {conEstado && (
                    <td className="px-3 py-1.5 pr-6">
                      <StatusIndicator tone={e.tone} label={e.label} />
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
          <tfoot className="sticky bottom-0 bg-surface-sunken font-semibold shadow-[inset_0_1px_0_var(--color-line-strong)]">
            <tr>
              <td className="px-3 py-3 pl-6" colSpan={3}>
                Total · {plan.length} cuotas
              </td>
              <td className="px-3 py-3 text-right whitespace-nowrap">
                {formatMoney(totales.capital)}
              </td>
              <td className="px-3 py-3 text-right whitespace-nowrap">
                {formatMoney(totales.intereses)}
              </td>
              <td className="px-3 py-3 text-right whitespace-nowrap">
                {formatMoney(totales.total)}
              </td>
              <td colSpan={conEstado ? 2 : 1} />
            </tr>
          </tfoot>
        </table>
      </div>
      <ul className="divide-y divide-line sm:hidden">
        {plan.map((c) => {
          const e = estadoCuota(c)
          return (
            <li key={c.numero} className="px-5 py-3 text-sm tabular-nums">
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-semibold text-ink">
                  Cuota {c.numero} · {formatDate(c.vencimiento)}
                </span>
                <span className="font-semibold whitespace-nowrap text-ink">
                  {formatMoney(c.cuota)}
                </span>
              </div>
              <p className="text-ink-muted">
                Capital {formatMoney(c.amortizacion)} · Interés {formatMoney(c.interes)}
              </p>
              <p className="text-ink-muted">Saldo {formatMoney(c.saldo_final)}</p>
              {conEstado && (
                <div className="mt-1">
                  <StatusIndicator tone={e.tone} label={e.label} />
                </div>
              )}
            </li>
          )
        })}
        <li className="bg-surface-sunken px-5 py-3 text-sm font-semibold tabular-nums">
          Total {formatMoney(totales.total)} · intereses {formatMoney(totales.intereses)}
        </li>
      </ul>
    </>
  )
}

function Par({
  label,
  children,
  fuerte = false,
}: {
  label: string
  children: React.ReactNode
  fuerte?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 px-5 py-3 sm:px-6">
      <dt className="text-sm font-medium text-ink-muted">{label}</dt>
      <dd
        className={`text-right whitespace-nowrap text-ink tabular-nums ${fuerte ? 'text-lg font-semibold text-brand-900' : ''}`}
      >
        {children}
      </dd>
    </div>
  )
}

/** Resumen de una evaluación: cuota, afectación contra el tope y motivos que la impiden. */
export function ResumenEvaluacion({ ev, conIngreso }: { ev: Evaluacion; conIngreso: boolean }) {
  const viable = ev.impedimentos.length === 0
  const excede = ev.afectacion !== null && compararDecimal(ev.afectacion, ev.afectacion_maxima) > 0
  return (
    <div className="grid gap-4">
      {ev.tasa_es_ejemplo && (
        <Alert tone="warning" title="Tasa a confirmar">
          Las condiciones de esta línea son valores de ejemplo, todavía no aprobados por el
          Directorio. La simulación es orientativa.
        </Alert>
      )}
      {conIngreso &&
        (viable ? (
          <Alert tone="success" title="Cumple las condiciones de la línea">
            El préstamo se puede solicitar con estos datos. Lo otorga la Caja después de revisarlo.
          </Alert>
        ) : (
          <Alert tone="danger" title="No se puede otorgar con estos datos">
            <ul className="mt-1 grid list-disc gap-1 pl-5">
              {ev.impedimentos.map((i) => (
                <li key={i}>{i}</li>
              ))}
            </ul>
          </Alert>
        ))}
      <dl className="divide-y divide-line rounded-control border border-line bg-surface">
        <Par
          label={ev.sistema === 'FRANCES' ? 'Cuota mensual' : 'Primera cuota (la más alta)'}
          fuerte
        >
          {formatMoney(ev.cuota_maxima)}
        </Par>
        <Par label="Tasa nominal anual">{formatPercent(ev.tna)}</Par>
        <Par label="Sistema">{SISTEMA[ev.sistema].label}</Par>
        {ev.otras_cuotas !== '0.00' && (
          <Par label="Cuotas de otros préstamos vigentes">{formatMoney(ev.otras_cuotas)}</Par>
        )}
        {ev.afectacion !== null && (
          <div
            className={`flex items-baseline justify-between gap-4 px-5 py-3 sm:px-6 ${excede ? 'bg-danger-50 text-danger-700' : ''}`}
          >
            <dt className="text-sm font-medium">Afectación del ingreso neto</dt>
            <dd className="text-right font-semibold whitespace-nowrap tabular-nums">
              {formatPercent(ev.afectacion)}{' '}
              <span className="font-normal opacity-80">
                de {formatPercent(ev.afectacion_maxima)} máximo
              </span>
            </dd>
          </div>
        )}
        <Par label="Total de intereses">{formatMoney(ev.totales.intereses)}</Par>
        <Par label="Total a devolver" fuerte>
          {formatMoney(ev.totales.total)}
        </Par>
      </dl>
    </div>
  )
}

/** Buscador de escribanos del padrón (apellido, nombre, matrícula o CUIT). */
export function EscribanoPicker({
  label,
  value,
  onChange,
  excluir,
  opcional = false,
}: {
  label: string
  value: string
  onChange: (id: string) => void
  excluir?: string
  opcional?: boolean
}) {
  const [q, setQ] = useState('')
  const busqueda = useDeferredValue(q)
  const query = useQuery({
    queryKey: ['padron', 'escribanos', 'picker', busqueda],
    queryFn: () =>
      fetchEscribanos({
        page: 1,
        pageSize: 10,
        q: busqueda,
        estado: '',
        registroNumero: '',
        departamento: '',
      }),
    enabled: busqueda.trim().length >= 2,
  })
  const opciones = (query.data?.items ?? []).filter((e) => e.id !== excluir)
  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm font-medium text-ink">{label}</legend>
      <Field
        label={`Buscar ${label.toLowerCase()}`}
        className="[&>label]:sr-only"
        type="search"
        placeholder="Apellido, nombre o matrícula"
        value={q}
        onChange={(e) => {
          setQ(e.target.value)
        }}
        trailing={
          <Search aria-hidden="true" className="mr-3 size-4 text-ink-subtle" strokeWidth={2.25} />
        }
      />
      <Select
        label={`${label} elegido`}
        className="[&>label]:sr-only"
        value={value}
        disabled={opciones.length === 0 && !value}
        onChange={(e) => {
          onChange(e.target.value)
        }}
        options={[
          {
            value: '',
            label: opciones.length
              ? opcional
                ? 'Sin garante'
                : 'Elegí de la lista'
              : 'Buscá por lo menos 2 letras',
          },
          ...opciones.map((e) => ({
            value: e.id,
            label: `${e.apellido_nombre} · Mat. ${String(e.matricula_numero)}${e.estado_matricula !== 'ACTIVO' ? ` · ${e.estado_matricula.toLowerCase()}` : ''}`,
          })),
        ]}
      />
    </fieldset>
  )
}
