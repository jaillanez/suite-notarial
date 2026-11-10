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
import { formatDecimal, normalizeDecimalInput, normalizeTasaInput } from '../../lib/decimal'
import { fetchLineas, guardarLinea, type Linea, type Moneda, type Sistema } from './api'
import { CondicionesLinea, RequisitosLinea } from './componentes'
import { MONEDA, SISTEMA } from './labels'

const tasa = (v: string) => formatDecimal(v, 4).replace(/,?0+$/, '')

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
    tna: linea ? tasa(linea.tna) : '',
    afectacion_maxima: linea ? tasa(linea.afectacion_maxima) : '',
    requiere_garante: linea?.requiere_garante ?? false,
    moneda: linea?.moneda ?? 'ARS',
    garantia: linea?.garantia ?? '',
    requisito_conducta: linea?.requisito_conducta ?? '',
    relacion_capital_hipoteca: linea?.relacion_capital_hipoteca
      ? tasa(linea.relacion_capital_hipoteca)
      : '',
    requiere_certificado_ingresos: linea?.requiere_certificado_ingresos ?? false,
    requiere_certificado_bienes: linea?.requiere_certificado_bienes ?? false,
    antiguedad_minima_meses:
      linea?.antiguedad_minima_meses != null ? String(linea.antiguedad_minima_meses) : '',
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
          moneda: f.moneda,
          garantia: f.garantia.trim() || null,
          requisito_conducta: f.requisito_conducta.trim() || null,
          relacion_capital_hipoteca: f.relacion_capital_hipoteca.trim()
            ? normalizeTasaInput(f.relacion_capital_hipoteca)
            : null,
          requiere_certificado_ingresos: f.requiere_certificado_ingresos,
          requiere_certificado_bienes: f.requiere_certificado_bienes,
          antiguedad_minima_meses: f.antiguedad_minima_meses.trim()
            ? Number.parseInt(f.antiguedad_minima_meses, 10)
            : null,
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
  type Bandera =
    | 'requiere_garante'
    | 'requiere_certificado_ingresos'
    | 'requiere_certificado_bienes'
    | 'es_ejemplo'
    | 'is_active'
  const bind = (key: Exclude<keyof typeof f, 'sistema' | 'moneda' | Bandera>) => ({
    value: f[key],
    onChange: (e: { target: { value: string } }) => {
      setF((x) => ({ ...x, [key]: e.target.value }))
    },
    error: problem?.fieldErrors[key],
  })
  const check = (key: Bandera, label: string) => (
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
  const simbolo = MONEDA[f.moneda].simbolo
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
          label="Moneda"
          value={f.moneda}
          onChange={(e) => {
            setF((x) => ({ ...x, moneda: e.target.value as Moneda }))
          }}
          options={(Object.keys(MONEDA) as Moneda[]).map((m) => ({
            value: m,
            label: `${MONEDA[m].label} (${MONEDA[m].simbolo})`,
          }))}
        />
        {f.moneda === 'USD' && (
          <p className="text-sm text-ink-muted sm:col-span-2">
            Montos, cuotas e ingreso neto en dólares. La Caja todavía no fijó el tipo de cambio para
            evaluar la afectación junto con ingresos o préstamos en pesos.
          </p>
        )}
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
          label={`Monto mínimo (${simbolo})`}
          inputMode="decimal"
          className={num}
          {...bind('monto_minimo')}
        />
        <Field
          label={`Monto máximo (${simbolo})`}
          inputMode="decimal"
          className={num}
          {...bind('monto_maximo')}
        />
        <Field label="Garantía (opcional)" placeholder="Sola firma" {...bind('garantia')} />
        <Field
          label="Capital sobre el inmueble (%)"
          inputMode="decimal"
          hint="Solo hipotecarios. Opcional."
          className={num}
          {...bind('relacion_capital_hipoteca')}
        />
        <Field
          label="Antigüedad mínima en la matrícula (meses)"
          inputMode="numeric"
          hint="Opcional. Sin fecha de juramento no bloquea: queda como aviso."
          className={num}
          {...bind('antiguedad_minima_meses')}
        />
        <Field label="Requisito de conducta (opcional)" {...bind('requisito_conducta')} />
        <TextArea
          className="sm:col-span-2"
          label="Descripción (opcional)"
          {...bind('descripcion')}
        />
        <div className="grid gap-1 sm:col-span-2">
          {check('requiere_garante', 'Exige garante solidario matriculado')}
          {check('requiere_certificado_ingresos', 'Exige certificado de ingresos')}
          {check('requiere_certificado_bienes', 'Exige certificado de bienes y deudas')}
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
                <CondicionesLinea linea={l} />
                <div className="mt-2 grid gap-2">
                  <RequisitosLinea linea={l} />
                  {l.descripcion && <p className="text-sm text-ink-muted">{l.descripcion}</p>}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {l.moneda === 'USD' && <StatusIndicator tone="unknown" label="En dólares" />}
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
