import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Calculator, Check, Plus, Save, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { formatMoney, formatPercent, normalizeDecimalInput } from '../../lib/decimal'
import { useSession } from '../auth/session'
import { formatDate, todayIso } from '../padron/labels'
import {
  aprobarVigencia,
  fetchConceptos,
  fetchVigencias,
  proponerVigencia,
  rechazarVigencia,
  simular,
  type Concepto,
  type ReglaRedondeo,
  type Vigencia,
} from './api'
import { ESTADO_VIGENCIA, REDONDEO, TIPO, detalleValores, resumenValor } from './labels'

const opt = (value: string): string | null => {
  const v = normalizeDecimalInput(value)
  return v ? v : null
}

function ProponerDialog({
  concepto,
  open,
  onClose,
}: {
  concepto: Concepto
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    fecha_desde: '',
    fecha_hasta: '',
    porcentaje: '',
    monto_fijo: '',
    monto_minimo: '',
    monto_maximo: '',
    tasa_mensual: '',
    dias_gracia: '',
    regla_redondeo: 'HALF_UP' as ReglaRedondeo,
    resolucion_respaldo: '',
    motivo: '',
  })
  const t = concepto.tipo
  const save = useMutation({
    mutationFn: () =>
      proponerVigencia(concepto.id, {
        fecha_desde: form.fecha_desde,
        fecha_hasta: form.fecha_hasta || null,
        regla_redondeo: form.regla_redondeo,
        resolucion_respaldo: form.resolucion_respaldo.trim(),
        motivo: form.motivo.trim(),
        ...(t === 'PORCENTUAL_ACTO' && {
          porcentaje: opt(form.porcentaje),
          monto_minimo: opt(form.monto_minimo),
          monto_maximo: opt(form.monto_maximo),
        }),
        ...(t === 'FIJO_MENSUAL' && { monto_fijo: opt(form.monto_fijo) }),
        ...(t === 'TASA_MORA' && {
          tasa_mensual: opt(form.tasa_mensual),
          dias_gracia: form.dias_gracia ? Number.parseInt(form.dias_gracia, 10) : null,
        }),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['parametros'] })
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const bind = (key: Exclude<keyof typeof form, 'regla_redondeo'>) => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) => {
      setForm((f) => ({ ...f, [key]: e.target.value }))
    },
    error: problem?.fieldErrors[key],
  })
  const money = { inputMode: 'decimal' as const, className: '[&_input]:tabular-nums' }

  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Proponer nueva vigencia"
      description="Queda pendiente hasta que la apruebe otra persona. Si la vigencia actual no tiene fin, al aprobarse se cierra el día anterior al inicio de esta."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Enviando…"
            disabled={
              !form.fecha_desde ||
              form.resolucion_respaldo.trim().length < 3 ||
              form.motivo.trim().length < 5
            }
            onClick={() => {
              save.mutate()
            }}
          >
            Proponer
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {problem && (
          <div className="sm:col-span-2">
            <Alert tone="danger">{problem.detail}</Alert>
          </div>
        )}
        <Field label="Vigente desde" type="date" {...bind('fecha_desde')} />
        <Field
          label="Hasta (opcional)"
          type="date"
          hint="Vacío: sin fecha de fin."
          {...bind('fecha_hasta')}
        />
        {t === 'PORCENTUAL_ACTO' && (
          <>
            <Field label="Porcentaje (%)" placeholder="1,5" {...money} {...bind('porcentaje')} />
            <div aria-hidden="true" className="hidden sm:block" />
            <Field
              label="Mínimo ($, opcional)"
              placeholder="0,00"
              {...money}
              {...bind('monto_minimo')}
            />
            <Field
              label="Tope ($, opcional)"
              placeholder="Sin tope"
              {...money}
              {...bind('monto_maximo')}
            />
          </>
        )}
        {t === 'FIJO_MENSUAL' && (
          <Field
            label="Monto mensual ($)"
            placeholder="25.000,00"
            {...money}
            {...bind('monto_fijo')}
          />
        )}
        {t === 'TASA_MORA' && (
          <>
            <Field label="Tasa mensual (%)" placeholder="3" {...money} {...bind('tasa_mensual')} />
            <Field
              label="Días de gracia"
              inputMode="numeric"
              placeholder="10"
              {...bind('dias_gracia')}
            />
          </>
        )}
        <Select
          label="Redondeo"
          value={form.regla_redondeo}
          onChange={(e) => {
            setForm((f) => ({ ...f, regla_redondeo: e.target.value as ReglaRedondeo }))
          }}
          options={(Object.keys(REDONDEO) as ReglaRedondeo[]).map((r) => ({
            value: r,
            label: REDONDEO[r],
          }))}
          className="sm:col-span-2"
        />
        <Field
          label="Resolución que la respalda"
          placeholder="Res. Directorio 12/2026"
          className="sm:col-span-2"
          {...bind('resolucion_respaldo')}
        />
        <TextArea label="Motivo" className="sm:col-span-2" {...bind('motivo')} />
      </div>
    </Dialog>
  )
}

function RechazarDialog({ vigencia, onClose }: { vigencia: Vigencia | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [motivo, setMotivo] = useState('')
  const save = useMutation({
    mutationFn: () => rechazarVigencia(vigencia?.id ?? '', motivo.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['parametros'] })
      setMotivo('')
      onClose()
    },
  })
  return (
    <Dialog
      open={vigencia !== null}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={`Rechazar la versión ${String(vigencia?.version ?? '')}`}
      description="El rechazo es definitivo; quien la propuso puede cargar una propuesta nueva."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="danger"
            icon={X}
            busy={save.isPending}
            busyLabel="Rechazando…"
            disabled={motivo.trim().length < 5}
            onClick={() => {
              save.mutate()
            }}
          >
            Rechazar
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <TextArea
          label="Motivo del rechazo"
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

function Simulador({ concepto }: { concepto: Concepto }) {
  const [fecha, setFecha] = useState(todayIso())
  const [base, setBase] = useState('')
  const [monto, setMonto] = useState('')
  const [vencimiento, setVencimiento] = useState('')
  const [pago, setPago] = useState('')
  const run = useMutation({
    mutationFn: () =>
      simular({
        concepto_codigo: concepto.codigo,
        fecha,
        ...(concepto.tipo === 'PORCENTUAL_ACTO' && { base_imponible: normalizeDecimalInput(base) }),
        ...(concepto.tipo === 'TASA_MORA' && {
          monto: normalizeDecimalInput(monto),
          vencimiento,
          fecha_pago: pago,
        }),
      }),
  })
  return (
    <Panel
      className="mt-6"
      title="Simulador"
      description="Calcula con la vigencia aprobada a la fecha elegida, sin guardar nada."
    >
      <div className="grid gap-4 px-5 py-5 sm:grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] sm:px-6">
        <Field
          label="Fecha de cálculo"
          type="date"
          value={fecha}
          onChange={(e) => {
            setFecha(e.target.value)
          }}
        />
        {concepto.tipo === 'PORCENTUAL_ACTO' && (
          <Field
            label="Base imponible ($)"
            inputMode="decimal"
            value={base}
            onChange={(e) => {
              setBase(e.target.value)
            }}
            className="[&_input]:tabular-nums"
          />
        )}
        {concepto.tipo === 'TASA_MORA' && (
          <>
            <Field
              label="Monto adeudado ($)"
              inputMode="decimal"
              value={monto}
              onChange={(e) => {
                setMonto(e.target.value)
              }}
              className="[&_input]:tabular-nums"
            />
            <Field
              label="Vencimiento"
              type="date"
              value={vencimiento}
              onChange={(e) => {
                setVencimiento(e.target.value)
              }}
            />
            <Field
              label="Fecha de pago"
              type="date"
              value={pago}
              onChange={(e) => {
                setPago(e.target.value)
              }}
            />
          </>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-4 border-t border-line px-5 py-4 sm:px-6">
        <Button
          icon={Calculator}
          busy={run.isPending}
          busyLabel="Calculando…"
          onClick={() => {
            run.mutate()
          }}
        >
          Calcular
        </Button>
        {run.isSuccess && (
          <div aria-live="polite">
            <p className="text-2xl font-semibold text-brand-900 tabular-nums">
              {formatMoney(run.data.resultado)}
            </p>
            <p className="text-sm text-ink-muted tabular-nums">
              Versión {run.data.vigencia.version} ·{' '}
              {concepto.tipo === 'PORCENTUAL_ACTO'
                ? `${formatPercent(run.data.vigencia.porcentaje)} sobre ${formatMoney(normalizeDecimalInput(base))}, con mínimo y tope`
                : `${formatPercent(run.data.vigencia.tasa_mensual)} mensual · ${String(run.data.dias_mora ?? 0)} días computables`}
              {run.data.vigencia.es_ejemplo && ' · valor de ejemplo, no oficial'}
            </p>
          </div>
        )}
      </div>
      {run.isError && (
        <div className="px-5 pb-4 sm:px-6">
          <Alert tone="danger">{toProblem(run.error).detail}</Alert>
        </div>
      )}
    </Panel>
  )
}

export function ConceptoPage() {
  const { id = '' } = useParams()
  const { user, can } = useSession()
  const queryClient = useQueryClient()
  const conceptos = useQuery({
    queryKey: ['parametros', 'conceptos', todayIso()],
    queryFn: () => fetchConceptos(todayIso()),
  })
  const vigencias = useQuery({
    queryKey: ['parametros', 'vigencias', id],
    queryFn: () => fetchVigencias(id),
  })
  const [proponiendo, setProponiendo] = useState(false)
  const [rechazando, setRechazando] = useState<Vigencia | null>(null)
  const aprobar = useMutation({
    mutationFn: aprobarVigencia,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['parametros'] })
    },
  })

  const concepto = conceptos.data?.find((c) => c.id === id)
  if (conceptos.isPending || vigencias.isPending) {
    return <span className="block h-48 w-full animate-pulse rounded-panel bg-brand-50" />
  }
  if (conceptos.isError || vigencias.isError || !concepto) {
    return (
      <Alert tone="danger">
        {conceptos.error || vigencias.error
          ? toProblem(conceptos.error ?? vigencias.error).detail
          : 'El concepto no existe.'}
      </Alert>
    )
  }

  const historial = vigencias.data
  const puedeAprobar = can('parameters:approve')

  return (
    <>
      <Link
        to="/parametros"
        className="mb-6 inline-flex min-h-11 items-center gap-2 text-sm font-semibold no-underline hover:underline"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Parámetros previsionales
      </Link>
      <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-brand-900 sm:text-[1.75rem]">
            {concepto.nombre}
          </h1>
          <p className="mt-2 text-ink-muted">
            <span className="font-mono">{concepto.codigo}</span> · {TIPO[concepto.tipo].label}
          </p>
          <p className="mt-1 max-w-[65ch] text-sm text-ink-muted">{TIPO[concepto.tipo].ayuda}</p>
        </div>
        {can('parameters:write') && concepto.is_active && (
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => {
              setProponiendo(true)
            }}
          >
            Proponer vigencia
          </Button>
        )}
      </div>

      {aprobar.isError && (
        <div className="mb-6">
          <Alert tone="danger">{toProblem(aprobar.error).detail}</Alert>
        </div>
      )}

      <Panel
        title="Vigencias"
        description="De la más reciente a la más antigua. Los valores de una vigencia nunca cambian."
      >
        {historial.length === 0 ? (
          <p className="px-5 py-6 text-sm text-ink-muted sm:px-6">
            Sin vigencias. Proponé la primera para que el concepto se pueda calcular.
          </p>
        ) : (
          <ol className="divide-y divide-line">
            {historial.map((v) => {
              const estado = ESTADO_VIGENCIA[v.estado]
              const propia = v.creado_por === user?.email
              return (
                <li key={v.id} className="px-5 py-5 sm:px-6">
                  <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-ink">Versión {v.version}</span>
                        <StatusIndicator tone={estado.tone} label={estado.label} />
                        {v.es_ejemplo && (
                          <StatusIndicator tone="warning" label="Valor de ejemplo" />
                        )}
                      </p>
                      <p className="mt-1 text-sm text-ink-muted tabular-nums">
                        Del {formatDate(v.fecha_desde)}{' '}
                        {v.fecha_hasta ? `al ${formatDate(v.fecha_hasta)}` : 'en adelante'}
                      </p>
                    </div>
                    <p className="text-xl font-semibold text-ink tabular-nums">
                      {resumenValor(concepto.tipo, v)}
                    </p>
                  </div>
                  <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                    {detalleValores(concepto.tipo, v).map(([label, value]) => (
                      <div key={label} className="flex justify-between gap-4">
                        <dt className="text-ink-muted">{label}</dt>
                        <dd className="text-right text-ink tabular-nums">{value}</dd>
                      </div>
                    ))}
                  </dl>
                  <p className="mt-3 max-w-[65ch] text-sm text-ink">{v.motivo}</p>
                  <p className="mt-1 text-xs text-ink-muted tabular-nums">
                    {v.resolucion_respaldo} · Propuesta por {v.creado_por ?? '—'} el{' '}
                    {formatLocalDateTime(new Date(v.created_at))}
                    {v.aprobado_por && v.fecha_aprobacion
                      ? ` · Aprobada por ${v.aprobado_por} el ${formatLocalDateTime(new Date(v.fecha_aprobacion))}`
                      : ''}
                  </p>
                  {v.motivo_rechazo && (
                    <p className="mt-2 text-sm text-danger-700">Rechazo: {v.motivo_rechazo}</p>
                  )}
                  {v.estado === 'PENDIENTE_APROBACION' && puedeAprobar && (
                    <div className="mt-4 flex flex-wrap items-center gap-3">
                      <Button
                        variant="primary"
                        icon={Check}
                        disabled={propia}
                        busy={aprobar.isPending && aprobar.variables === v.id}
                        busyLabel="Aprobando…"
                        onClick={() => {
                          aprobar.mutate(v.id)
                        }}
                      >
                        Aprobar
                      </Button>
                      <Button
                        variant="danger"
                        icon={X}
                        onClick={() => {
                          setRechazando(v)
                        }}
                      >
                        Rechazar
                      </Button>
                      {propia && (
                        <span className="text-sm text-ink-muted">
                          La propusiste vos: la aprueba otra persona.
                        </span>
                      )}
                    </div>
                  )}
                </li>
              )
            })}
          </ol>
        )}
      </Panel>

      {concepto.tipo !== 'FIJO_MENSUAL' && <Simulador concepto={concepto} />}

      <ProponerDialog
        key={String(proponiendo)}
        concepto={concepto}
        open={proponiendo}
        onClose={() => {
          setProponiendo(false)
        }}
      />
      <RechazarDialog
        vigencia={rechazando}
        onClose={() => {
          setRechazando(null)
        }}
      />
    </>
  )
}
