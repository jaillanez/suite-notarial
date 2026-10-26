import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, FilePlus2 } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { normalizeDecimalInput } from '../../lib/decimal'
import { crearSolicitud, fetchLineas, simular } from './api'
import { EscribanoPicker, PlanCuotas, ResumenEvaluacion } from './componentes'

const DECIMAL = /^\d+(\.\d{1,2})?$/

export function SolicitudPage() {
  const navigate = useNavigate()
  const lineas = useQuery({ queryKey: ['prestamos', 'lineas'], queryFn: fetchLineas })
  const activas = (lineas.data ?? []).filter((l) => l.is_active)
  const [form, setForm] = useState({
    escribano: '',
    garante: '',
    linea: '',
    capital: '',
    cuotas: '',
    ingreso: '',
    observaciones: '',
  })
  const linea = activas.find((l) => l.id === form.linea) ?? activas[0]
  const datos = useDeferredValue({
    capital: normalizeDecimalInput(form.capital),
    cuotas: Number.parseInt(form.cuotas, 10),
    ingreso: normalizeDecimalInput(form.ingreso),
    escribano: form.escribano,
    garante: form.garante,
  })
  const completo =
    Boolean(linea) &&
    Boolean(datos.escribano) &&
    DECIMAL.test(datos.capital) &&
    datos.cuotas > 0 &&
    DECIMAL.test(datos.ingreso)
  const evaluacion = useQuery({
    queryKey: ['prestamos', 'evaluacion', linea?.id, datos],
    queryFn: () =>
      simular({
        linea_id: linea?.id ?? '',
        capital: datos.capital,
        cuotas: datos.cuotas,
        ingreso_neto: datos.ingreso,
        escribano_id: datos.escribano,
        garante_escribano_id: datos.garante || null,
      }),
    enabled: completo,
    placeholderData: keepPreviousData,
    retry: false,
  })
  const guardar = useMutation({
    mutationFn: () =>
      crearSolicitud({
        escribano_id: form.escribano,
        linea_id: linea?.id ?? '',
        capital: datos.capital,
        cuotas: datos.cuotas,
        ingreso_neto: datos.ingreso,
        garante_escribano_id: form.garante || null,
        observaciones: form.observaciones.trim() || null,
      }),
    onSuccess: (p) => {
      void navigate(`/prestamos/${p.id}`)
    },
  })
  const set = (key: keyof typeof form) => (valor: string) => {
    setForm((f) => ({ ...f, [key]: valor }))
  }
  const viable = evaluacion.data !== undefined && evaluacion.data.impedimentos.length === 0

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
        title="Nueva solicitud de préstamo"
        description="Se evalúa mientras completás los datos. La solicitud la resuelve otra persona con permiso para otorgar."
      />
      <div className="grid items-start gap-6 lg:grid-cols-[24rem_minmax(0,1fr)]">
        <Panel title="Solicitud">
          <div className="grid gap-5 px-5 py-4 sm:px-6">
            <EscribanoPicker label="Escribano" value={form.escribano} onChange={set('escribano')} />
            <Select
              label="Línea de crédito"
              value={linea?.id ?? ''}
              onChange={(e) => {
                set('linea')(e.target.value)
              }}
              options={activas.map((l) => ({
                value: l.id,
                label: l.es_ejemplo ? `${l.nombre} (a confirmar)` : l.nombre,
              }))}
            />
            <div className="grid grid-cols-2 gap-4">
              <Field
                label="Capital ($)"
                inputMode="decimal"
                className="[&_input]:tabular-nums"
                value={form.capital}
                onChange={(e) => {
                  set('capital')(e.target.value)
                }}
              />
              <Field
                label="Cuotas"
                inputMode="numeric"
                className="[&_input]:tabular-nums"
                value={form.cuotas}
                onChange={(e) => {
                  set('cuotas')(e.target.value)
                }}
              />
            </div>
            <Field
              label="Ingreso neto mensual ($)"
              inputMode="decimal"
              hint="Promedio acreditado, neto de retenciones."
              className="[&_input]:tabular-nums"
              value={form.ingreso}
              onChange={(e) => {
                set('ingreso')(e.target.value)
              }}
            />
            <EscribanoPicker
              label={linea?.requiere_garante ? 'Garante (obligatorio)' : 'Garante (opcional)'}
              value={form.garante}
              excluir={form.escribano}
              opcional={!linea?.requiere_garante}
              onChange={set('garante')}
            />
            <TextArea
              label="Observaciones (opcional)"
              maxLength={2000}
              value={form.observaciones}
              onChange={(e) => {
                set('observaciones')(e.target.value)
              }}
            />
          </div>
          <div className="flex justify-end border-t border-line bg-surface-sunken px-5 py-4 sm:px-6">
            <Button
              variant="primary"
              icon={FilePlus2}
              busy={guardar.isPending}
              busyLabel="Cargando…"
              disabled={!completo || !viable || evaluacion.isPlaceholderData}
              onClick={() => {
                guardar.mutate()
              }}
            >
              Cargar solicitud
            </Button>
          </div>
        </Panel>
        <div
          aria-live="polite"
          className={`grid gap-6 transition-opacity duration-150 ${evaluacion.isPlaceholderData ? 'opacity-60' : ''}`}
        >
          {guardar.isError && <Alert tone="danger">{toProblem(guardar.error).detail}</Alert>}
          {!completo && (
            <Panel>
              <p className="px-5 py-10 text-center text-ink-muted sm:px-6">
                Elegí el escribano y completá capital, cuotas e ingreso neto para evaluar.
              </p>
            </Panel>
          )}
          {completo && evaluacion.isError && (
            <Alert tone="danger">{toProblem(evaluacion.error).detail}</Alert>
          )}
          {completo && evaluacion.data && (
            <>
              <ResumenEvaluacion ev={evaluacion.data} conIngreso />
              <Panel title="Cuadro de amortización (proyectado)">
                <PlanCuotas
                  plan={evaluacion.data.plan}
                  totales={evaluacion.data.totales}
                  conEstado={false}
                />
              </Panel>
            </>
          )}
        </div>
      </div>
    </>
  )
}
