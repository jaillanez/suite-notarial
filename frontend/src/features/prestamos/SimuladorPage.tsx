import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { Link } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Field } from '../../components/ui/Field'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import { formatMoney, formatPercent, normalizeDecimalInput } from '../../lib/decimal'
import { fetchLineas, simular } from './api'
import { PlanCuotas, ResumenEvaluacion } from './componentes'
import { SISTEMA } from './labels'

const DECIMAL = /^\d+(\.\d{1,2})?$/

export function SimuladorPage() {
  const lineas = useQuery({ queryKey: ['prestamos', 'lineas'], queryFn: fetchLineas })
  const activas = (lineas.data ?? []).filter((l) => l.is_active)
  const [lineaId, setLineaId] = useState('')
  const linea = activas.find((l) => l.id === lineaId) ?? activas[0]
  const [form, setForm] = useState({ capital: '', cuotas: '', ingreso: '' })
  const datos = useDeferredValue({
    capital: normalizeDecimalInput(form.capital),
    cuotas: Number.parseInt(form.cuotas, 10),
    ingreso: normalizeDecimalInput(form.ingreso),
  })
  const listo = Boolean(linea) && DECIMAL.test(datos.capital) && datos.cuotas > 0
  const conIngreso = DECIMAL.test(datos.ingreso)
  const query = useQuery({
    queryKey: ['prestamos', 'simulacion', linea?.id, datos],
    queryFn: () =>
      simular({
        linea_id: linea?.id ?? '',
        capital: datos.capital,
        cuotas: datos.cuotas,
        ingreso_neto: conIngreso ? datos.ingreso : null,
      }),
    enabled: listo,
    placeholderData: keepPreviousData,
    retry: false,
  })

  return (
    <>
      <Link
        to="/prestamos"
        className="mb-6 inline-flex min-h-11 items-center gap-2 text-sm font-medium"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Préstamos
      </Link>
      <PageHeader
        title="Simular un préstamo"
        description="Elegí la línea, el monto y el plazo. Con tu ingreso neto mensual se calcula cuánto de él compromete la cuota, sumando otros préstamos vigentes."
      />
      <div className="grid items-start gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <Panel title="Datos">
          <div className="grid gap-4 px-5 py-4 sm:px-6">
            {lineas.isError && <Alert tone="danger">{toProblem(lineas.error).detail}</Alert>}
            <Select
              label="Línea de crédito"
              value={linea?.id ?? ''}
              disabled={activas.length === 0}
              onChange={(e) => {
                setLineaId(e.target.value)
              }}
              options={activas.map((l) => ({
                value: l.id,
                label: l.es_ejemplo ? `${l.nombre} (a confirmar)` : l.nombre,
              }))}
            />
            {linea && (
              <p className="text-sm text-ink-muted tabular-nums">
                {SISTEMA[linea.sistema].label} · TNA {formatPercent(linea.tna)} · de{' '}
                {formatMoney(linea.monto_minimo)} a {formatMoney(linea.monto_maximo)} ·{' '}
                {linea.plazo_minimo} a {linea.plazo_maximo} cuotas · tope{' '}
                {formatPercent(linea.afectacion_maxima)} del ingreso
                {linea.requiere_garante ? ' · exige garante' : ''}
              </p>
            )}
            <Field
              label="Capital ($)"
              inputMode="decimal"
              className="[&_input]:tabular-nums"
              value={form.capital}
              onChange={(e) => {
                setForm((f) => ({ ...f, capital: e.target.value }))
              }}
            />
            <Field
              label="Cantidad de cuotas"
              inputMode="numeric"
              className="[&_input]:tabular-nums"
              value={form.cuotas}
              onChange={(e) => {
                setForm((f) => ({ ...f, cuotas: e.target.value }))
              }}
            />
            <Field
              label="Ingreso neto mensual ($)"
              inputMode="decimal"
              hint="Opcional: para calcular la afectación."
              className="[&_input]:tabular-nums"
              value={form.ingreso}
              onChange={(e) => {
                setForm((f) => ({ ...f, ingreso: e.target.value }))
              }}
            />
          </div>
        </Panel>
        <div
          aria-live="polite"
          className={`grid gap-6 transition-opacity duration-150 ${query.isPlaceholderData ? 'opacity-60' : ''}`}
        >
          {!listo && (
            <Panel>
              <p className="px-5 py-10 text-center text-ink-muted sm:px-6">
                Completá el capital y la cantidad de cuotas para ver el plan.
              </p>
            </Panel>
          )}
          {listo && query.isError && <Alert tone="danger">{toProblem(query.error).detail}</Alert>}
          {listo && query.data && (
            <>
              <ResumenEvaluacion ev={query.data} conIngreso={conIngreso} />
              <Panel title="Cuadro de amortización" description={SISTEMA[query.data.sistema].ayuda}>
                <PlanCuotas plan={query.data.plan} totales={query.data.totales} conEstado={false} />
              </Panel>
            </>
          )}
        </div>
      </div>
    </>
  )
}
