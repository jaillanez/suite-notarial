import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Pencil, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import {
  formatDecimal,
  formatMoney,
  formatPercent,
  normalizeDecimalInput,
  normalizeTasaInput,
} from '../../lib/decimal'
import { fetchLineas, guardarLinea, type Linea, type Sistema } from './api'
import { SISTEMA } from './labels'

function LineaDialog({
  linea,
  open,
  onClose,
}: {
  linea?: Linea
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [f, setF] = useState({
    codigo: linea?.codigo ?? '',
    nombre: linea?.nombre ?? '',
    descripcion: linea?.descripcion ?? '',
    sistema: linea?.sistema ?? 'FRANCES',
    plazo_minimo: String(linea?.plazo_minimo ?? ''),
    plazo_maximo: String(linea?.plazo_maximo ?? ''),
    monto_minimo: linea ? formatDecimal(linea.monto_minimo) : '',
    monto_maximo: linea ? formatDecimal(linea.monto_maximo) : '',
    tna: linea ? formatDecimal(linea.tna, 4).replace(/,?0+$/, '') : '',
    afectacion_maxima: linea ? formatDecimal(linea.afectacion_maxima, 4).replace(/,?0+$/, '') : '',
    requiere_garante: linea?.requiere_garante ?? false,
    es_ejemplo: linea?.es_ejemplo ?? true,
    is_active: linea?.is_active ?? true,
  })
  const save = useMutation({
    mutationFn: () =>
      guardarLinea(
        {
          codigo: f.codigo.trim().toUpperCase(),
          nombre: f.nombre.trim(),
          descripcion: f.descripcion.trim() || null,
          sistema: f.sistema,
          plazo_minimo: Number.parseInt(f.plazo_minimo, 10),
          plazo_maximo: Number.parseInt(f.plazo_maximo, 10),
          monto_minimo: normalizeDecimalInput(f.monto_minimo),
          monto_maximo: normalizeDecimalInput(f.monto_maximo),
          tna: normalizeTasaInput(f.tna),
          afectacion_maxima: normalizeTasaInput(f.afectacion_maxima),
          requiere_garante: f.requiere_garante,
          es_ejemplo: f.es_ejemplo,
          is_active: f.is_active,
        },
        linea?.id,
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['prestamos', 'lineas'] })
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const bind = (
    key: Exclude<keyof typeof f, 'sistema' | 'requiere_garante' | 'es_ejemplo' | 'is_active'>,
  ) => ({
    value: f[key],
    onChange: (e: { target: { value: string } }) => {
      setF((x) => ({ ...x, [key]: e.target.value }))
    },
    error: problem?.fieldErrors[key],
  })
  const check = (key: 'requiere_garante' | 'es_ejemplo' | 'is_active', label: string) => (
    <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm text-ink">
      <input
        type="checkbox"
        className="size-4 accent-brand-800"
        checked={f[key]}
        onChange={(e) => {
          setF((x) => ({ ...x, [key]: e.target.checked }))
        }}
      />
      {label}
    </label>
  )
  const num = 'tabular-nums [&_input]:tabular-nums'
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={linea ? `Editar ${linea.nombre}` : 'Nueva línea de crédito'}
      description="Los cambios valen para solicitudes nuevas: los préstamos ya pedidos conservan sus condiciones."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            busy={save.isPending}
            busyLabel="Guardando…"
            onClick={() => {
              save.mutate()
            }}
          >
            Guardar
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
        <Field
          label="Código"
          placeholder="LINEA_COMUN"
          disabled={linea !== undefined}
          {...bind('codigo')}
        />
        <Field label="Nombre" {...bind('nombre')} />
        <Select
          className="sm:col-span-2"
          label="Sistema de amortización"
          value={f.sistema}
          onChange={(e) => {
            setF((x) => ({ ...x, sistema: e.target.value as Sistema }))
          }}
          options={(Object.keys(SISTEMA) as Sistema[]).map((s) => ({
            value: s,
            label: `${SISTEMA[s].label}: ${SISTEMA[s].ayuda}`,
          }))}
        />
        <Field
          label="Tasa nominal anual (%)"
          inputMode="decimal"
          className={num}
          {...bind('tna')}
        />
        <Field
          label="Tope de afectación (%)"
          inputMode="decimal"
          hint="De la cuota sobre el ingreso neto."
          className={num}
          {...bind('afectacion_maxima')}
        />
        <Field
          label="Plazo mínimo (cuotas)"
          inputMode="numeric"
          className={num}
          {...bind('plazo_minimo')}
        />
        <Field
          label="Plazo máximo (cuotas)"
          inputMode="numeric"
          className={num}
          {...bind('plazo_maximo')}
        />
        <Field
          label="Monto mínimo ($)"
          inputMode="decimal"
          className={num}
          {...bind('monto_minimo')}
        />
        <Field
          label="Monto máximo ($)"
          inputMode="decimal"
          className={num}
          {...bind('monto_maximo')}
        />
        <TextArea
          className="sm:col-span-2"
          label="Descripción (opcional)"
          {...bind('descripcion')}
        />
        <div className="grid gap-1 sm:col-span-2">
          {check('requiere_garante', 'Exige garante solidario matriculado')}
          {check('es_ejemplo', 'Valores a confirmar (todavía no aprobados por el Directorio)')}
          {check('is_active', 'Habilitada para nuevas solicitudes')}
        </div>
      </div>
    </Dialog>
  )
}

export function LineasPage() {
  const query = useQuery({ queryKey: ['prestamos', 'lineas'], queryFn: fetchLineas })
  const [editando, setEditando] = useState<{ open: boolean; item?: Linea }>({ open: false })
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
        title="Líneas de crédito"
        description="Condiciones que fija el Directorio para cada línea. Cada cambio queda en la auditoría."
      />
      <Panel
        title="Líneas"
        actions={
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => {
              setEditando({ open: true })
            }}
          >
            Nueva línea
          </Button>
        }
      >
        {query.isError && (
          <div className="px-5 py-4 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}
        <ul className="divide-y divide-line">
          {query.data?.length === 0 && (
            <li className="px-5 py-10 text-center text-ink-muted sm:px-6">
              Todavía no hay líneas de crédito.
            </li>
          )}
          {query.data?.map((l) => (
            <li
              key={l.id}
              className="flex flex-wrap items-start justify-between gap-3 px-5 py-4 sm:px-6"
            >
              <div className="min-w-0">
                <p className="font-semibold text-ink">
                  {l.nombre} <span className="font-normal text-ink-muted">· {l.codigo}</span>
                </p>
                <p className="text-sm text-ink-muted tabular-nums">
                  {SISTEMA[l.sistema].label} · TNA {formatPercent(l.tna)} · {l.plazo_minimo} a{' '}
                  {l.plazo_maximo} cuotas · {formatMoney(l.monto_minimo)} a{' '}
                  {formatMoney(l.monto_maximo)} · tope {formatPercent(l.afectacion_maxima)}
                  {l.requiere_garante ? ' · exige garante' : ''}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {l.es_ejemplo && <StatusIndicator tone="warning" label="A confirmar" />}
                {!l.is_active && <StatusIndicator tone="unknown" label="Deshabilitada" />}
                <Button
                  variant="ghost"
                  icon={Pencil}
                  onClick={() => {
                    setEditando({ open: true, item: l })
                  }}
                >
                  Editar
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
      <LineaDialog
        key={editando.item?.id ?? `nueva-${String(editando.open)}`}
        linea={editando.item}
        open={editando.open}
        onClose={() => {
          setEditando({ open: false })
        }}
      />
    </>
  )
}
