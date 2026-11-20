import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowLeft, FilePlus2 } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import { normalizeDecimalInput } from '../../lib/decimal'
import { useSession } from '../auth/session'
import { fetchLineas, simular } from './api'
import { CondicionesLinea, PlanCuotas, RequisitosLinea, ResumenEvaluacion } from './componentes'
import { LEYENDA_USD, MONEDA, SISTEMA, fueraDeLinea, importe } from './labels'

const DECIMAL = /^\d+(\.\d{1,2})?$/

export function SimuladorPage() {
  const { can } = useSession()
  const navigate = useNavigate()
  const solicita = can('prestamos:manage') || can('prestamos:read_own')
  const lineas = useQuery({ queryKey: ['prestamos', 'lineas'], queryFn: fetchLineas })
  const activas = (lineas.data ?? []).filter((l) => l.is_active)
  const [lineaId, setLineaId] = useState('')
  const linea = activas.find((l) => l.id === lineaId) ?? activas[0]
  const [form, setForm] = useState({ capital: '', cuotas: '' })
  const usd = linea?.moneda === 'USD'
  const simbolo = MONEDA[linea?.moneda ?? 'ARS'].simbolo
  const datos = useDeferredValue({
    capital: normalizeDecimalInput(form.capital),
    cuotas: Number.parseInt(form.cuotas, 10),
  })
  // Fuera de lo que admite la línea no se simula: se dice en el campo.
  const errores = fueraDeLinea(linea, datos.capital, datos.cuotas)
  const listo =
    Boolean(linea) &&
    DECIMAL.test(datos.capital) &&
    datos.cuotas > 0 &&
    !errores.capital &&
    !errores.cuotas
  const query = useQuery({
    queryKey: ['prestamos', 'simulacion', linea?.id, datos],
    queryFn: () =>
      simular({
        linea_id: linea?.id ?? '',
        capital: datos.capital,
        cuotas: datos.cuotas,
        ingreso_neto: null,
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
        description="Elegí la línea, el monto y el plazo. Se calcula el ingreso neto mensual mínimo para que la cuota, sumada a la de otros préstamos vigentes, no supere el tope de la línea."
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
              <>
                <CondicionesLinea linea={linea} />
                <RequisitosLinea linea={linea} />
              </>
            )}
            <Field
              label={`Capital ${usd ? 'en dólares ' : ''}(${simbolo})`}
              inputMode="decimal"
              className="[&_input]:tabular-nums"
              hint={
                linea &&
                `De ${importe(linea.monto_minimo, linea.moneda)} a ${importe(linea.monto_maximo, linea.moneda)}.`
              }
              error={errores.capital}
              value={form.capital}
              onChange={(e) => {
                setForm((f) => ({ ...f, capital: e.target.value }))
              }}
            />
            <Field
              label="Cantidad de cuotas"
              inputMode="numeric"
              className="[&_input]:tabular-nums"
              hint={linea && `De ${String(linea.plazo_minimo)} a ${String(linea.plazo_maximo)}.`}
              error={errores.cuotas}
              value={form.cuotas}
              onChange={(e) => {
                setForm((f) => ({ ...f, cuotas: e.target.value }))
              }}
            />
            {usd && <p className="text-sm text-ink-muted">{LEYENDA_USD}</p>}
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
              <ResumenEvaluacion ev={query.data} conIngreso={false} />
              {solicita && linea && (
                <div>
                  <Button
                    variant="primary"
                    icon={FilePlus2}
                    onClick={() => {
                      const q = new URLSearchParams({
                        linea: linea.id,
                        capital: datos.capital,
                        cuotas: String(datos.cuotas),
                      })
                      void navigate(`/prestamos/nueva?${q.toString()}`)
                    }}
                  >
                    Solicitar este préstamo
                  </Button>
                </div>
              )}
              <Panel title="Cuadro de amortización" description={SISTEMA[query.data.sistema].ayuda}>
                <PlanCuotas
                  plan={query.data.plan}
                  totales={query.data.totales}
                  conEstado={false}
                  moneda={query.data.moneda}
                />
              </Panel>
            </>
          )}
        </div>
      </div>
    </>
  )
}
