import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Camera,
  Download,
  FilePenLine,
  Paperclip,
  Plus,
  ReceiptText,
  ScanText,
  TriangleAlert,
  CircleX,
  Send,
  Trash2,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { Panel } from '../../components/ui/Panel'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { formatMoney, formatPercent } from '../../lib/decimal'
import { useSession } from '../auth/session'
import { CARGO, formatDate, todayIso } from '../padron/labels'
import { AdjuntarComprobanteDialog } from '../pagos/AdjuntarComprobanteDialog'
import { PERIODO_TASA } from '../parametros/labels'
import {
  agregarActo,
  bajaActo,
  descargarBoleta,
  emitirBoleta,
  fetchDeclaracion,
  fetchLiquidacion,
  presentar,
  rectificar,
  type Acto,
  type Boleta,
  type ControlProtocolo,
  type Hueco,
  type DeclaracionDetalle,
  type Liquidacion,
} from './api'
import { actoCompleto, actoInput, actoSiguiente, actoSugerido, type ActoForm } from './acto'
import { ActoCampos } from './ActoCampos'
import { useVerificacionActo } from './verificacion'
import { ResultadoVerificacion } from './VerificacionActo'
import {
  ESTADO_BOLETA,
  ESTADO_DDJJ,
  PROTOCOLO,
  categoriaDe,
  formatCodigo,
  formatPeriodo,
  registroLabel,
} from './labels'

/** Plazo máximo de una boleta (el backend aplica el mismo límite). */
const MAX_DIAS_PAGO = 60

/** "N° 48", o "N° 48 · acto 2" para los demás actos de una misma escritura. */
function numeroDeActo(a: Acto): string {
  const numero = `N° ${String(a.numero_escritura)}`
  return a.orden_en_escritura > 1 ? `${numero} · acto ${String(a.orden_en_escritura)}` : numero
}

function sumarDias(iso: string, dias: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + dias)
  return d.toISOString().slice(0, 10)
}

function useInvalidate(id: string) {
  const queryClient = useQueryClient()
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['ddjj', 'declaracion', id] })
    await queryClient.invalidateQueries({ queryKey: ['ddjj', 'declaraciones'] })
  }
}

// --------------------------------------------------------------------------- liquidación

function Row({
  label,
  hint,
  value,
  strong = false,
}: {
  label: string
  hint?: string
  value: string
  strong?: boolean
}) {
  return (
    <div
      className={`flex items-baseline justify-between gap-4 px-5 py-3 sm:px-6 ${strong ? 'bg-surface-sunken' : ''}`}
    >
      <dt
        className={`min-w-0 text-sm ${strong ? 'font-semibold text-ink' : 'font-medium text-ink-muted'}`}
      >
        {label}
        {hint && (
          <span className="block font-normal text-ink-muted tabular-nums sm:ml-1.5 sm:inline">
            {hint}
          </span>
        )}
      </dt>
      <dd
        className={`shrink-0 whitespace-nowrap text-ink tabular-nums ${strong ? 'font-semibold' : ''}`}
      >
        {value}
      </dd>
    </div>
  )
}

type Importes = Pick<
  Liquidacion,
  | 'total_protocolos'
  | 'aporte_minimo'
  | 'excedente'
  | 'aporte_medico'
  | 'cantidad_aportes_medicos'
  | 'total_en_termino'
  | 'dias_mora'
  | 'interes_mora'
  | 'tramos_mora'
  | 'total_a_pagar'
>

function Desglose({ liq }: { liq: Importes }) {
  const medicos = liq.cantidad_aportes_medicos
  return (
    <dl className="divide-y divide-line">
      <Row label="Total protocolos" value={formatMoney(liq.total_protocolos)} />
      <Row label="Aporte mínimo" value={formatMoney(liq.aporte_minimo)} />
      <Row label="Excedente" hint="(lo que supera el mínimo)" value={formatMoney(liq.excedente)} />
      <Row
        label="Aporte médico asistencial"
        hint={`(${String(medicos)} ${medicos === 1 ? 'aporte' : 'aportes'})`}
        value={formatMoney(liq.aporte_medico)}
      />
      <Row label="Total en término" value={formatMoney(liq.total_en_termino)} strong />
      <Row
        label="Interés por pago fuera de término"
        hint={`(${String(liq.dias_mora)} ${liq.dias_mora === 1 ? 'día' : 'días'})`}
        value={formatMoney(liq.interes_mora)}
      />
      {liq.tramos_mora.length > 1 && (
        <div className="px-5 py-2 sm:px-6">
          <p className="text-sm text-ink-muted">La tasa cambió durante el atraso:</p>
          <ul className="mt-1 space-y-1">
            {liq.tramos_mora.map((t) => (
              <li
                key={t.desde}
                className="flex items-baseline justify-between gap-4 text-sm text-ink-muted tabular-nums"
              >
                <span className="min-w-0">
                  Del {formatDate(t.desde)} al {formatDate(t.hasta)}: {t.dias}{' '}
                  {t.dias === 1 ? 'día' : 'días'} al {formatPercent(t.tasa)}{' '}
                  {PERIODO_TASA[t.periodo_tasa]}
                </span>
                <span className="shrink-0 whitespace-nowrap">{formatMoney(t.interes)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t border-line-strong px-5 py-4 sm:px-6">
        <dt className="font-semibold text-brand-900">Total a pagar</dt>
        <dd className="text-xl font-semibold text-brand-900 tabular-nums">
          {formatMoney(liq.total_a_pagar)}
        </dd>
      </div>
    </dl>
  )
}

function AvisoEjemplo() {
  return (
    <Alert tone="warning" title="Incluye valores a confirmar">
      Algún parámetro usado en este cálculo (por ejemplo, la tasa de mora) todavía no está
      confirmado como oficial por la Caja.
    </Alert>
  )
}

function LiquidacionBorrador({
  ddjj,
  onPresentar,
}: {
  ddjj: DeclaracionDetalle
  onPresentar: (fechaPago: string, liq: Liquidacion) => void
}) {
  const hoy = todayIso()
  const [fechaPago, setFechaPago] = useState(hoy)
  const valida = fechaPago >= hoy && fechaPago <= sumarDias(hoy, MAX_DIAS_PAGO)
  const query = useQuery({
    queryKey: ['ddjj', 'declaracion', ddjj.id, 'liquidacion', fechaPago, ddjj.actos.length],
    queryFn: () => fetchLiquidacion(ddjj.id, fechaPago),
    enabled: valida,
    retry: false,
    // Al cambiar la fecha se conservan los importes anteriores mientras recalcula.
    placeholderData: keepPreviousData,
  })
  const terminado = ddjj.periodo < hoy.slice(0, 7)

  return (
    <Panel
      title="Liquidación"
      description="Calculada por la Caja con los parámetros vigentes del período. Es una vista previa: los importes quedan fijos al presentar."
      footer={
        query.data
          ? `Vencimiento del período: ${formatDate(query.data.vencimiento)}. Pagando después, se suma interés por mora.`
          : undefined
      }
    >
      <div className="flex flex-col gap-4 border-b border-line px-5 py-4 sm:flex-row sm:items-end sm:justify-between sm:px-6">
        <Field
          label="Fecha de pago"
          type="date"
          className="sm:w-56 [&_input]:tabular-nums"
          min={hoy}
          max={sumarDias(hoy, MAX_DIAS_PAGO)}
          value={fechaPago}
          error={valida ? undefined : `Entre hoy y ${String(MAX_DIAS_PAGO)} días más.`}
          onChange={(e) => {
            setFechaPago(e.target.value)
          }}
        />
        {ddjj.puede_operar && (
          <Button
            variant="primary"
            icon={Send}
            disabled={!query.data || query.isPlaceholderData || !terminado}
            onClick={() => {
              if (query.data) onPresentar(fechaPago, query.data)
            }}
          >
            Presentar y emitir boleta
          </Button>
        )}
      </div>
      {ddjj.puede_operar && !terminado && (
        <div className="px-5 pt-4 sm:px-6">
          <Alert tone="info">
            El período {formatPeriodo(ddjj.periodo)} todavía está en curso: podés cargar actos, pero
            la declaración se presenta una vez terminado el mes.
          </Alert>
        </div>
      )}
      {query.data?.usa_valores_de_ejemplo && (
        <div className="px-5 pt-4 pb-2 sm:px-6">
          <AvisoEjemplo />
        </div>
      )}
      {query.isError && (
        <div className="px-5 py-4 sm:px-6">
          <Alert tone="danger" title="No se puede calcular">
            {toProblem(query.error).detail}
          </Alert>
        </div>
      )}
      <div
        aria-live="polite"
        aria-busy={query.isFetching}
        className={`transition-opacity duration-150 ${query.isPlaceholderData ? 'opacity-60' : ''}`}
      >
        {query.isPending && valida && (
          <div className="grid gap-3 px-5 py-4 sm:px-6">
            {Array.from({ length: 5 }, (_, i) => (
              <span key={i} className="block h-6 animate-pulse rounded-control bg-brand-50" />
            ))}
          </div>
        )}
        {query.data && <Desglose liq={query.data} />}
      </div>
    </Panel>
  )
}

// --------------------------------------------------------------------------- actos

function ActoDialog({
  ddjj,
  open,
  onClose,
}: {
  ddjj: DeclaracionDetalle
  open: boolean
  onClose: () => void
}) {
  const invalidate = useInvalidate(ddjj.id)
  // Completado con lo más probable: mismo escribano, protocolo y fecha que el último acto, y
  // el número de escritura que sigue.
  const [form, setForm] = useState(() => actoSugerido(ddjj, todayIso()))
  const [agregado, setAgregado] = useState<string | null>(null)
  const { verificacion, bloqueado, actualizando } = useVerificacionActo(ddjj.id, form)
  const save = useMutation({
    mutationFn: ({ datos }: { datos: ActoForm; otro: boolean }) =>
      agregarActo(ddjj.id, actoInput(datos)),
    onSuccess: async (_, { datos, otro }) => {
      await invalidate()
      if (!otro) {
        onClose()
        return
      }
      setAgregado(`Escritura N° ${datos.numero_escritura} agregada. Seguí con la siguiente.`)
      setForm(actoSiguiente(datos, ddjj))
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const listo = actoCompleto(form) && !bloqueado
  const guardar = (otro: boolean) => {
    setAgregado(null)
    save.mutate({ datos: form, otro })
  }

  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Agregar acto"
      description={`Acto autorizado en ${formatPeriodo(ddjj.periodo)} por un escribano del registro. Viene completado con los datos del último acto: cambiá solo lo que difiere.`}
      footer={
        <>
          <Button onClick={onClose}>{agregado ? 'Terminar' : 'Cancelar'}</Button>
          <Button
            icon={Plus}
            busy={save.isPending && save.variables.otro}
            busyLabel="Agregando…"
            disabled={!listo || save.isPending}
            onClick={() => {
              guardar(true)
            }}
          >
            Agregar y cargar otro
          </Button>
          <Button
            variant="primary"
            icon={Plus}
            busy={save.isPending && !save.variables.otro}
            busyLabel="Agregando…"
            disabled={!listo || save.isPending}
            onClick={() => {
              guardar(false)
            }}
          >
            Agregar
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {agregado && <Alert tone="success">{agregado}</Alert>}
        {problem && <Alert tone="danger">{problem.detail}</Alert>}
        <ActoCampos
          ddjj={ddjj}
          form={form}
          problem={problem}
          onChange={(cambio) => {
            setForm((f) => {
              const nuevo = { ...f, ...cambio }
              // Al cambiar de protocolo, el número sugerido pasa al que sigue en ese protocolo.
              if (
                cambio.tipo_protocolo &&
                cambio.tipo_protocolo !== f.tipo_protocolo &&
                f.numero_escritura === String(ddjj.proximos_numeros[f.tipo_protocolo])
              ) {
                nuevo.numero_escritura = String(ddjj.proximos_numeros[cambio.tipo_protocolo])
              }
              return nuevo
            })
          }}
        />
        <ResultadoVerificacion verificacion={verificacion} actualizando={actualizando} />
      </div>
    </Dialog>
  )
}

function BajaDialog({
  ddjj,
  acto,
  onClose,
}: {
  ddjj: DeclaracionDetalle
  acto: Acto | null
  onClose: () => void
}) {
  const invalidate = useInvalidate(ddjj.id)
  const [motivo, setMotivo] = useState('')
  const baja = useMutation({
    mutationFn: () => bajaActo(ddjj.id, acto?.id ?? '', motivo.trim()),
    onSuccess: async () => {
      await invalidate()
      onClose()
    },
  })
  return (
    <Dialog
      open={acto !== null}
      onClose={onClose}
      title={acto ? `Quitar el acto ${numeroDeActo(acto)}` : 'Quitar el acto'}
      description="El acto deja de figurar en la declaración. Queda registrado quién lo quitó y por qué."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="danger"
            icon={Trash2}
            busy={baja.isPending}
            busyLabel="Quitando…"
            disabled={motivo.trim().length < 5}
            onClick={() => {
              baja.mutate()
            }}
          >
            Quitar acto
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {baja.isError && <Alert tone="danger">{toProblem(baja.error).detail}</Alert>}
        <TextArea
          label="Motivo"
          hint="Obligatorio, al menos 5 caracteres."
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

/** Avisos del libro de protocolo bajo un acto (ícono y texto en el tono del aviso). */
function ControlesActo({ controles }: { controles: ControlProtocolo[] | undefined }) {
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

function listarTramos(tramos: Hueco['tramos']): string {
  const partes = tramos.map((t) =>
    t.desde === t.hasta
      ? String(t.desde)
      : t.hasta === t.desde + 1
        ? `${String(t.desde)}, ${String(t.hasta)}`
        : `${String(t.desde)} a ${String(t.hasta)}`,
  )
  if (partes.length === 1) return partes[0] ?? ''
  return `${partes.slice(0, -1).join('; ')} y ${partes[partes.length - 1] ?? ''}`
}

/** Números de escritura salteados en el año: o se declaran o se declaran «sin efecto». */
function Huecos({ ddjj }: { ddjj: DeclaracionDetalle }) {
  if (ddjj.huecos.length === 0) return null
  return (
    <div className="border-b border-line px-5 py-4 sm:px-6">
      <Alert tone="warning" title="Hay números de escritura sin declarar este año">
        <ul className="space-y-1 tabular-nums">
          {ddjj.huecos.map((h) => (
            <li key={h.tipo_protocolo}>
              Protocolo {PROTOCOLO[h.tipo_protocolo].toLowerCase()}: {listarTramos(h.tramos)} (
              {h.total} {h.total === 1 ? 'número' : 'números'}).
            </li>
          ))}
        </ul>
        <p className="mt-2">
          Si alguna escritura no se otorgó, declarala con el tipo «Sin efecto» para que la
          numeración del protocolo quede completa.
        </p>
      </Alert>
    </div>
  )
}

function ActosPanel({ ddjj, aportes }: { ddjj: DeclaracionDetalle; aportes: Map<string, string> }) {
  const editable = ddjj.estado === 'BORRADOR' && ddjj.puede_operar
  const [adding, setAdding] = useState(false)
  const [quitando, setQuitando] = useState<Acto | null>(null)
  const aporteDe = (a: Acto) => a.aporte ?? aportes.get(a.id) ?? null
  const estimado = ddjj.estado === 'BORRADOR'

  return (
    <Panel
      title="Actos declarados"
      description={
        ddjj.actos.length === 0
          ? undefined
          : `${String(ddjj.actos.length)} ${ddjj.actos.length === 1 ? 'acto' : 'actos'}${estimado ? ' · aportes estimados hasta presentar' : ''}`
      }
      actions={
        editable ? (
          <div className="flex flex-wrap gap-3">
            {ddjj.escribanos.length > 0 && (
              <Link
                to={`/ddjj/${ddjj.id}/indice`}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-control border border-line-strong bg-surface px-4 text-sm font-semibold text-brand-800 no-underline transition-colors duration-150 ease-out-quint hover:border-brand-700 hover:bg-brand-50"
              >
                <Camera aria-hidden="true" className="size-4" strokeWidth={2.25} />
                Foto del índice
              </Link>
            )}
            {ddjj.escribanos.length > 0 && (
              <Link
                to={`/ddjj/${ddjj.id}/minuta`}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-control border border-line-strong bg-surface px-4 text-sm font-semibold text-brand-800 no-underline transition-colors duration-150 ease-out-quint hover:border-brand-700 hover:bg-brand-50"
              >
                <ScanText aria-hidden="true" className="size-4" strokeWidth={2.25} />
                Cargar desde la minuta
              </Link>
            )}
            <Button
              icon={Plus}
              disabled={ddjj.escribanos.length === 0}
              onClick={() => {
                setAdding(true)
              }}
            >
              Agregar acto
            </Button>
          </div>
        ) : undefined
      }
    >
      <Huecos ddjj={ddjj} />
      {ddjj.actos.length === 0 ? (
        <p className="px-5 py-8 text-center text-ink-muted sm:px-6">
          {editable
            ? 'Sin actos todavía. Si en el mes no hubo escrituras, la declaración se presenta igual y se paga el aporte mínimo.'
            : 'La declaración no tiene actos.'}
        </p>
      ) : (
        <>
          <table className="hidden w-full text-sm sm:table">
            <thead className="bg-surface-sunken text-xs font-semibold text-ink-muted">
              <tr>
                <th scope="col" className="px-6 py-2.5 text-left">
                  Escritura
                </th>
                <th scope="col" className="px-3 py-2.5 text-left">
                  Acto
                </th>
                <th scope="col" className="px-3 py-2.5 text-right">
                  Base imponible
                </th>
                <th scope="col" className="px-6 py-2.5 text-right">
                  Aporte
                </th>
                {editable && (
                  <th scope="col" className="w-0 pr-4">
                    <span className="sr-only">Acciones</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {ddjj.actos.map((a) => (
                <tr key={a.id} className="align-top">
                  <td className="px-6 py-3 whitespace-nowrap tabular-nums">
                    <span className="block font-semibold text-ink">{numeroDeActo(a)}</span>
                    <span className="block text-ink-muted">
                      {PROTOCOLO[a.tipo_protocolo]}
                      {a.folio !== null && ` · F. ${String(a.folio)}`}
                    </span>
                    <span className="block text-ink-muted">{formatDate(a.fecha_acto)}</span>
                  </td>
                  <td className="px-3 py-3">
                    <span className="block text-ink">{a.naturaleza}</span>
                    <span className="block text-ink-muted">{categoriaDe(a)}</span>
                    <span className="block text-ink-muted">
                      {a.escribano} ({CARGO[a.cargo]})
                    </span>
                    <ControlesActo controles={ddjj.controles[a.id]} />
                  </td>
                  <td className="px-3 py-3 text-right whitespace-nowrap text-ink tabular-nums">
                    {a.categoria === 'ESCRITURA_CON_VALOR' ? formatMoney(a.base_imponible) : '—'}
                  </td>
                  <td className="px-6 py-3 text-right font-semibold whitespace-nowrap text-ink tabular-nums">
                    {formatMoney(aporteDe(a))}
                  </td>
                  {editable && (
                    <td className="pr-4 py-1.5">
                      <Button
                        variant="ghost"
                        aria-label={`Quitar el acto ${numeroDeActo(a)}`}
                        onClick={() => {
                          setQuitando(a)
                        }}
                        icon={Trash2}
                      >
                        Quitar
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="divide-y divide-line sm:hidden">
            {ddjj.actos.map((a) => (
              <li key={a.id} className="px-5 py-4">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-semibold text-ink tabular-nums">
                    {numeroDeActo(a)} · {PROTOCOLO[a.tipo_protocolo]}
                  </span>
                  <span className="font-semibold text-ink tabular-nums">
                    {formatMoney(aporteDe(a))}
                  </span>
                </div>
                <p className="mt-1 text-sm text-ink">
                  {a.naturaleza} · {categoriaDe(a)}
                </p>
                <p className="text-sm text-ink-muted tabular-nums">
                  {a.escribano} · {formatDate(a.fecha_acto)}
                </p>
                <ControlesActo controles={ddjj.controles[a.id]} />
                {a.categoria === 'ESCRITURA_CON_VALOR' && (
                  <p className="text-sm text-ink-muted tabular-nums">
                    Base imponible{' '}
                    <span className="whitespace-nowrap">{formatMoney(a.base_imponible)}</span>
                  </p>
                )}
                {editable && (
                  <Button
                    variant="ghost"
                    className="-ml-4 mt-1"
                    icon={Trash2}
                    onClick={() => {
                      setQuitando(a)
                    }}
                  >
                    Quitar
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      <ActoDialog
        key={`acto-${String(adding)}`}
        ddjj={ddjj}
        open={adding}
        onClose={() => {
          setAdding(false)
        }}
      />
      <BajaDialog
        key={quitando?.id ?? 'ninguno'}
        ddjj={ddjj}
        acto={quitando}
        onClose={() => {
          setQuitando(null)
        }}
      />
    </Panel>
  )
}

// --------------------------------------------------------------------------- boletas

/** Mientras Tesorería revisa un comprobante, la boleta no se reemite ni se rectifica. */
function enRevision(ddjj: DeclaracionDetalle): boolean {
  return ddjj.boletas.some((b) => b.comprobante?.estado === 'PENDIENTE_REVISION')
}

function EstadoComprobanteBoleta({ boleta }: { boleta: Boleta }) {
  const c = boleta.comprobante
  if (!c || boleta.estado === 'ANULADA') return null
  if (c.estado === 'RECHAZADO' && boleta.estado === 'PENDIENTE') {
    return (
      <Alert tone="danger" title="Tesorería rechazó el comprobante">
        {c.motivo_rechazo} La boleta sigue pendiente: adjuntá un comprobante nuevo.
      </Alert>
    )
  }
  if (c.estado === 'PENDIENTE_REVISION') {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <StatusIndicator tone="warning" label="Comprobante en revisión" />
        <span className="text-sm text-ink-muted tabular-nums">
          Enviado el {formatLocalDateTime(new Date(c.created_at)).slice(0, 10)} por{' '}
          {formatMoney(c.importe_declarado)}. Tesorería confirma el pago contra el extracto.
        </span>
      </div>
    )
  }
  return null
}

function BoletaItem({ boleta, puedeAdjuntar }: { boleta: Boleta; puedeAdjuntar: boolean }) {
  const [adjuntando, setAdjuntando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const descarga = useMutation({
    mutationFn: () => descargarBoleta(boleta),
    onError: (e) => {
      setError(toProblem(e).detail)
    },
    onSuccess: () => {
      setError(null)
    },
  })
  const estado = ESTADO_BOLETA[boleta.estado]
  return (
    <li className="px-5 py-4 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-ink tabular-nums">
            Boleta N° {boleta.numero}
            <span className="ml-2 font-normal text-ink-muted">
              emitida el {formatDate(boleta.fecha_emision)}
            </span>
          </p>
          <p className="text-sm text-ink-muted tabular-nums">
            Pagar hasta el {formatDate(boleta.fecha_pago)}
            {boleta.dias_mora > 0 &&
              ` · ${String(boleta.dias_mora)} ${boleta.dias_mora === 1 ? 'día' : 'días'} de mora`}
            {' · '}
            <span className="whitespace-nowrap">
              Código {formatCodigo(boleta.codigo_verificacion)}
            </span>
          </p>
          {boleta.motivo_anulacion && (
            <p className="text-sm text-ink-muted">Anulada: {boleta.motivo_anulacion}</p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`text-lg font-semibold whitespace-nowrap tabular-nums ${boleta.estado === 'ANULADA' ? 'text-ink-muted line-through' : 'text-brand-900'}`}
          >
            {formatMoney(boleta.total_a_pagar)}
          </span>
          <StatusIndicator tone={estado.tone} label={estado.label} />
        </div>
      </div>
      <div className="mt-3 empty:hidden">
        <EstadoComprobanteBoleta boleta={boleta} />
      </div>
      {boleta.estado !== 'ANULADA' && (
        <div className="mt-3 flex flex-wrap gap-3">
          <Button
            icon={Download}
            busy={descarga.isPending}
            busyLabel="Preparando PDF…"
            onClick={() => {
              descarga.mutate()
            }}
          >
            Descargar PDF
          </Button>
          {puedeAdjuntar &&
            boleta.estado === 'PENDIENTE' &&
            boleta.comprobante?.estado !== 'PENDIENTE_REVISION' && (
              <Button
                icon={Paperclip}
                onClick={() => {
                  setAdjuntando(true)
                }}
              >
                Adjuntar comprobante
              </Button>
            )}
        </div>
      )}
      <AdjuntarComprobanteDialog
        key={`adjuntar-${String(adjuntando)}`}
        boleta={boleta}
        open={adjuntando}
        onClose={() => {
          setAdjuntando(false)
        }}
      />
      {error && (
        <div className="mt-3">
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
    </li>
  )
}

function BoletasPanel({ ddjj, onNueva }: { ddjj: DeclaracionDetalle; onNueva: () => void }) {
  const { can } = useSession()
  const vigente = ddjj.boletas.find((b) => b.estado !== 'ANULADA')
  const puedeEmitir =
    ddjj.estado === 'PRESENTADA' &&
    ddjj.puede_operar &&
    vigente?.estado !== 'PAGADA' &&
    !enRevision(ddjj)
  return (
    <Panel
      title="Boletas"
      description="La más reciente arriba. Al emitir una nueva para otra fecha de pago, la pendiente anterior se anula."
      actions={
        puedeEmitir ? (
          <Button icon={ReceiptText} onClick={onNueva}>
            Nueva boleta
          </Button>
        ) : undefined
      }
    >
      {ddjj.boletas.length === 0 ? (
        <p className="px-5 py-8 text-center text-ink-muted sm:px-6">
          La boleta se emite al presentar la declaración.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {ddjj.boletas.map((b) => (
            <BoletaItem key={b.id} boleta={b} puedeAdjuntar={can('comprobantes:upload')} />
          ))}
        </ul>
      )}
    </Panel>
  )
}

// --------------------------------------------------------------------------- acciones

function PresentarDialog({
  ddjj,
  pedido,
  onClose,
}: {
  ddjj: DeclaracionDetalle
  pedido: { fechaPago: string; liq: Liquidacion } | null
  onClose: () => void
}) {
  const invalidate = useInvalidate(ddjj.id)
  const [observaciones, setObservaciones] = useState('')
  const save = useMutation({
    mutationFn: () =>
      presentar(ddjj.id, {
        fecha_pago: pedido?.fechaPago ?? '',
        observaciones: observaciones.trim() || null,
      }),
    onSuccess: async () => {
      await invalidate()
      onClose()
    },
  })
  return (
    <Dialog
      open={pedido !== null}
      onClose={onClose}
      title={`Presentar la DDJJ ${formatPeriodo(ddjj.periodo)}`}
      description="Los aportes de cada acto quedan fijos y se emite la boleta. Para corregir algo después, hay que rectificar la declaración."
      footer={
        <>
          <Button onClick={onClose}>Revisar de nuevo</Button>
          <Button
            variant="primary"
            icon={Send}
            busy={save.isPending}
            busyLabel="Presentando…"
            onClick={() => {
              save.mutate()
            }}
          >
            Presentar y emitir boleta
          </Button>
        </>
      }
    >
      {pedido && (
        <div className="grid gap-4">
          {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
          <dl className="divide-y divide-line rounded-control border border-line">
            <Row label="Registro" value={registroLabel(ddjj.registro)} />
            <Row
              label="Actos"
              value={`${String(ddjj.actos.length)} ${ddjj.actos.length === 1 ? 'acto' : 'actos'}`}
            />
            <Row label="Pagar hasta" value={formatDate(pedido.fechaPago)} />
            <Row label="Total a pagar" value={formatMoney(pedido.liq.total_a_pagar)} strong />
          </dl>
          {pedido.liq.usa_valores_de_ejemplo && <AvisoEjemplo />}
          <TextArea
            label="Observaciones (opcional)"
            maxLength={1000}
            value={observaciones}
            onChange={(e) => {
              setObservaciones(e.target.value)
            }}
          />
        </div>
      )}
    </Dialog>
  )
}

function NuevaBoletaDialog({
  ddjj,
  open,
  onClose,
}: {
  ddjj: DeclaracionDetalle
  open: boolean
  onClose: () => void
}) {
  const invalidate = useInvalidate(ddjj.id)
  const hoy = todayIso()
  const [fechaPago, setFechaPago] = useState(hoy)
  const save = useMutation({
    mutationFn: () => emitirBoleta(ddjj.id, fechaPago),
    onSuccess: async () => {
      await invalidate()
      onClose()
    },
  })
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Nueva boleta"
      description="Para pagar en otra fecha. Los importes de la declaración no cambian; si la fecha es posterior al vencimiento, se suma el interés por mora."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={ReceiptText}
            busy={save.isPending}
            busyLabel="Emitiendo…"
            disabled={!fechaPago}
            onClick={() => {
              save.mutate()
            }}
          >
            Emitir boleta
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <Field
          label="Fecha de pago"
          type="date"
          className="[&_input]:tabular-nums"
          min={hoy}
          max={sumarDias(hoy, MAX_DIAS_PAGO)}
          value={fechaPago}
          hint={
            ddjj.vencimiento ? `El período vence el ${formatDate(ddjj.vencimiento)}.` : undefined
          }
          onChange={(e) => {
            setFechaPago(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

function RectificarDialog({
  ddjj,
  open,
  onClose,
}: {
  ddjj: DeclaracionDetalle
  open: boolean
  onClose: () => void
}) {
  const navigate = useNavigate()
  const invalidate = useInvalidate(ddjj.id)
  const save = useMutation({
    mutationFn: () => rectificar(ddjj.id),
    onSuccess: async (nueva) => {
      await invalidate()
      onClose()
      void navigate(`/ddjj/${nueva.id}`)
    },
  })
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={`Rectificar la DDJJ ${formatPeriodo(ddjj.periodo)}`}
      description="Se abre una rectificativa en borrador con una copia de los actos para corregirlos. Esta declaración queda como antecedente y su boleta pendiente se anula."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={FilePenLine}
            busy={save.isPending}
            busyLabel="Abriendo…"
            onClick={() => {
              save.mutate()
            }}
          >
            Abrir rectificativa
          </Button>
        </>
      }
    >
      {save.isError ? (
        <Alert tone="danger">{toProblem(save.error).detail}</Alert>
      ) : (
        <p className="text-sm text-ink-muted">
          La nueva boleta se emite cuando presentes la rectificativa.
        </p>
      )}
    </Dialog>
  )
}

// --------------------------------------------------------------------------- página

function Dato({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-sm font-medium text-ink-muted">{label}</dt>
      <dd className="mt-0.5 break-words text-ink tabular-nums">{children}</dd>
    </div>
  )
}

export function DeclaracionPage() {
  const { id = '' } = useParams()
  const query = useQuery({
    queryKey: ['ddjj', 'declaracion', id],
    queryFn: () => fetchDeclaracion(id),
  })
  const ddjj = query.data
  const [pedido, setPedido] = useState<{ fechaPago: string; liq: Liquidacion } | null>(null)
  const [nuevaBoleta, setNuevaBoleta] = useState(false)
  const [rectificando, setRectificando] = useState(false)
  // Aportes estimados del borrador (los trae la vista previa de la liquidación).
  const preview = useQuery({
    queryKey: ['ddjj', 'declaracion', id, 'liquidacion', todayIso(), ddjj?.actos.length ?? 0],
    queryFn: () => fetchLiquidacion(id, todayIso()),
    enabled: ddjj?.estado === 'BORRADOR',
    retry: false,
  })
  const vigente = ddjj?.boletas.find((b) => b.estado !== 'ANULADA') ?? ddjj?.boletas[0]
  const aportes = new Map((preview.data?.aportes ?? []).map((a) => [a.acto_id, a.aporte]))

  return (
    <>
      <Link to="/ddjj" className="mb-6 inline-flex min-h-11 items-center gap-2 text-sm font-medium">
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Declaraciones juradas
      </Link>
      {query.isError && <Alert tone="danger">{toProblem(query.error).detail}</Alert>}
      {query.isPending && (
        <div aria-busy="true" aria-live="polite" className="grid gap-4">
          <span className="block h-9 w-72 animate-pulse rounded-control bg-brand-50" />
          <span className="block h-48 animate-pulse rounded-panel bg-brand-50" />
        </div>
      )}
      {ddjj && (
        <div className="grid gap-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight text-brand-900 tabular-nums sm:text-[1.75rem]">
                DDJJ {formatPeriodo(ddjj.periodo)}
                {ddjj.numero_rectificativa > 0 &&
                  ` · Rectificativa ${String(ddjj.numero_rectificativa)}`}
              </h1>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <span className="text-ink-muted">{registroLabel(ddjj.registro)}</span>
                <StatusIndicator
                  tone={ESTADO_DDJJ[ddjj.estado].tone}
                  label={ESTADO_DDJJ[ddjj.estado].label}
                />
              </div>
            </div>
            {ddjj.estado === 'PRESENTADA' && ddjj.puede_operar && !enRevision(ddjj) && (
              <div className="flex flex-wrap gap-3">
                <Button
                  icon={FilePenLine}
                  onClick={() => {
                    setRectificando(true)
                  }}
                >
                  Rectificar
                </Button>
              </div>
            )}
          </div>

          {ddjj.estado === 'RECTIFICADA' && (
            <Alert tone="info" title="Declaración reemplazada">
              Fue corregida por una rectificativa del mismo período. Se conserva como antecedente;
              sus boletas quedaron anuladas.
            </Alert>
          )}
          {ddjj.rectifica_a_id && (
            <p className="text-sm text-ink-muted">
              Rectifica a la{' '}
              <Link to={`/ddjj/${ddjj.rectifica_a_id}`}>declaración anterior del período</Link>.
            </p>
          )}

          <Panel>
            <dl className="grid grid-cols-2 gap-4 px-5 py-4 sm:grid-cols-4 sm:px-6">
              <Dato label="Vencimiento">{formatDate(ddjj.vencimiento)}</Dato>
              <Dato label="Departamento">{ddjj.registro.departamento}</Dato>
              <Dato label="Presentada">
                {ddjj.fecha_presentacion
                  ? formatLocalDateTime(new Date(ddjj.fecha_presentacion))
                  : 'Todavía no'}
              </Dato>
              <Dato label="Presentada por">{ddjj.presentada_por ?? '—'}</Dato>
            </dl>
            {ddjj.observaciones && (
              <p className="border-t border-line px-5 py-3 text-sm text-ink sm:px-6">
                <span className="font-medium text-ink-muted">Observaciones: </span>
                {ddjj.observaciones}
              </p>
            )}
          </Panel>

          <ActosPanel ddjj={ddjj} aportes={aportes} />

          {ddjj.estado === 'BORRADOR' ? (
            <LiquidacionBorrador
              ddjj={ddjj}
              onPresentar={(fechaPago, liq) => {
                setPedido({ fechaPago, liq })
              }}
            />
          ) : (
            vigente && (
              <Panel
                title="Liquidación presentada"
                description={`Importes fijados al presentar, según la boleta N° ${String(vigente.numero)}.`}
              >
                <Desglose liq={vigente} />
              </Panel>
            )
          )}

          {ddjj.estado !== 'BORRADOR' && (
            <BoletasPanel
              ddjj={ddjj}
              onNueva={() => {
                setNuevaBoleta(true)
              }}
            />
          )}

          <PresentarDialog
            key={pedido ? `${pedido.fechaPago}-${pedido.liq.total_a_pagar}` : 'cerrado'}
            ddjj={ddjj}
            pedido={pedido}
            onClose={() => {
              setPedido(null)
            }}
          />
          <NuevaBoletaDialog
            key={`boleta-${String(nuevaBoleta)}`}
            ddjj={ddjj}
            open={nuevaBoleta}
            onClose={() => {
              setNuevaBoleta(false)
            }}
          />
          <RectificarDialog
            ddjj={ddjj}
            open={rectificando}
            onClose={() => {
              setRectificando(false)
            }}
          />
        </div>
      )}
    </>
  )
}
