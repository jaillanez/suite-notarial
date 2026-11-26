import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Plus, Save, Search } from 'lucide-react'
import { useState, type SyntheticEvent } from 'react'
import { Link } from 'react-router'

import { StatusIndicator, type Tone } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { Pagination } from '../../components/ui/Pagination'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { formatMoney, normalizeDecimalInput } from '../../lib/decimal'
import { useSession } from '../auth/session'
import { formatPeriodo, registroLabel } from '../ddjj/labels'
import {
  aprobarAjuste,
  fetchAjustes,
  fetchBoletaParaAjustar,
  proponerAjuste,
  rechazarAjuste,
  type Ajuste,
  type BoletaParaAjustar,
  type ConceptoAjuste,
  type EstadoAjuste,
  type TipoAjuste,
} from './api'

const CONCEPTO: Record<ConceptoAjuste, string> = {
  REDONDEO: 'Redondeo (centavos de más o de menos)',
  REDUCCION_INTERESES: 'Rebaja de intereses (Junta)',
  CONDONACION: 'Condonación (Junta)',
  DIFERENCIA_RECTIFICATIVA: 'Diferencia de una rectificativa',
  OTRO: 'Otro',
}

const CON_RESOLUCION: ConceptoAjuste[] = ['REDUCCION_INTERESES', 'CONDONACION']

const ESTADO: Record<EstadoAjuste, { label: string; tone: Tone }> = {
  PROPUESTO: { label: 'Por aprobar', tone: 'warning' },
  APROBADO: { label: 'Aprobado', tone: 'success' },
  RECHAZADO: { label: 'Rechazado', tone: 'danger' },
}

function fecha(iso: string): string {
  return formatLocalDateTime(new Date(iso))
}

function useRefrescar() {
  const queryClient = useQueryClient()
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['ajustes'] })
  }
}

/** Un ajuste en una lista: qué, cuánto, por qué, quién y en qué quedó. */
function FilaAjuste({
  a,
  conBoleta,
  onRechazar,
}: {
  a: Ajuste
  conBoleta: boolean
  onRechazar: (a: Ajuste) => void
}) {
  const refrescar = useRefrescar()
  const aprobar = useMutation({
    mutationFn: () => aprobarAjuste(a.id),
    onSuccess: refrescar,
  })
  const estado = ESTADO[a.estado]
  return (
    <li className="px-5 py-4 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <p className="font-semibold text-ink">
            {a.tipo === 'CREDITO' ? 'Crédito' : 'Débito'} de{' '}
            <span className="tabular-nums">{formatMoney(a.importe)}</span>
            {conBoleta && (
              <span className="font-normal text-ink-muted">
                {' · '}Boleta N° <span className="tabular-nums">{a.boleta_numero}</span>
              </span>
            )}
          </p>
          <p className="text-sm text-ink-muted">
            {CONCEPTO[a.concepto]}
            {a.resolucion && ` · ${a.resolucion}`}
          </p>
        </div>
        <StatusIndicator tone={estado.tone} label={estado.label} />
      </div>
      <p className="mt-2 max-w-[65ch] text-ink">{a.justificacion}</p>
      <p className="mt-1 text-xs text-ink-muted">
        Propuso {a.propuesto_por ?? '—'} el {fecha(a.propuesto_en)}
        {a.resuelto_en &&
          ` · ${a.estado === 'APROBADO' ? 'Aprobó' : 'Rechazó'} ${a.resuelto_por ?? '—'} el ${fecha(a.resuelto_en)}`}
      </p>
      {a.motivo_rechazo && (
        <p className="mt-1 text-sm text-danger-700">Motivo del rechazo: {a.motivo_rechazo}</p>
      )}
      {aprobar.isError && (
        <div className="mt-3">
          <Alert tone="danger">{toProblem(aprobar.error).detail}</Alert>
        </div>
      )}
      {a.puede_resolver && (
        <div className="mt-3 flex flex-wrap gap-3">
          <Button
            icon={Check}
            busy={aprobar.isPending}
            busyLabel="Aprobando…"
            onClick={() => {
              aprobar.mutate()
            }}
          >
            Aprobar
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              onRechazar(a)
            }}
          >
            Rechazar
          </Button>
        </div>
      )}
    </li>
  )
}

function RechazarDialog({ ajuste, onClose }: { ajuste: Ajuste | null; onClose: () => void }) {
  const refrescar = useRefrescar()
  const [motivo, setMotivo] = useState('')
  const save = useMutation({
    mutationFn: (id: string) => rechazarAjuste(id, motivo.trim()),
    onSuccess: async () => {
      await refrescar()
      setMotivo('')
      onClose()
    },
  })
  return (
    <Dialog
      open={ajuste !== null}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Rechazar el ajuste"
      description="El ajuste no se aplica. El rechazo queda en la auditoría y quien lo propuso ve el motivo."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="danger"
            busy={save.isPending}
            busyLabel="Rechazando…"
            disabled={motivo.trim().length < 5}
            onClick={() => {
              if (ajuste) save.mutate(ajuste.id)
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
          label="Motivo"
          value={motivo}
          maxLength={1000}
          hint="Obligatorio. Mínimo 5 caracteres."
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

function ProponerDialog({
  datos,
  open,
  onClose,
}: {
  datos: BoletaParaAjustar
  open: boolean
  onClose: () => void
}) {
  const refrescar = useRefrescar()
  const vacio = {
    tipo: 'CREDITO' as TipoAjuste,
    concepto: 'REDONDEO' as ConceptoAjuste,
    importe: '',
    resolucion: '',
    justificacion: '',
  }
  const [form, setForm] = useState(vacio)
  const pideResolucion = CON_RESOLUCION.includes(form.concepto)
  const save = useMutation({
    mutationFn: () =>
      proponerAjuste({
        boleta_id: datos.boleta.id,
        tipo: form.tipo,
        concepto: form.concepto,
        importe: normalizeDecimalInput(form.importe),
        justificacion: form.justificacion.trim(),
        resolucion: form.resolucion.trim() || null,
      }),
    onSuccess: async () => {
      await refrescar()
      setForm(vacio)
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const completo =
    form.importe.trim() !== '' &&
    form.justificacion.trim().length >= 10 &&
    (!pideResolucion || form.resolucion.trim().length >= 3)
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={`Proponer un ajuste a la boleta N° ${String(datos.boleta.numero)}`}
      description={`Queda pagar ${formatMoney(datos.boleta.saldo_a_pagar)}. El ajuste cuenta recién cuando lo aprueba otra persona.`}
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Proponiendo…"
            disabled={!completo}
            onClick={() => {
              save.mutate()
            }}
          >
            Proponer ajuste
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {problem && Object.keys(problem.fieldErrors).length === 0 && (
          <Alert tone="danger">{problem.detail}</Alert>
        )}
        <fieldset>
          <legend className="text-sm font-medium text-ink">Tipo</legend>
          <div className="mt-1.5 grid gap-2 sm:grid-cols-2">
            {(
              [
                ['CREDITO', 'Crédito', 'Baja lo que se debe de la boleta.'],
                ['DEBITO', 'Débito', 'Sube lo que se debe de la boleta.'],
              ] as const
            ).map(([valor, titulo, detalle]) => (
              <label
                key={valor}
                className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-control border px-3 py-2.5 transition-colors duration-150 ease-out-quint ${form.tipo === valor ? 'border-brand-700 bg-brand-50' : 'border-line-strong bg-surface hover:bg-brand-50'}`}
              >
                <input
                  type="radio"
                  name="tipo-ajuste"
                  checked={form.tipo === valor}
                  onChange={() => {
                    setForm((f) => ({ ...f, tipo: valor }))
                  }}
                  className="mt-0.5 size-5 shrink-0 cursor-pointer accent-brand-800"
                />
                <span className="text-sm">
                  <span className="block font-medium text-ink">{titulo}</span>
                  <span className="block text-ink-muted">{detalle}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <Select
          label="Concepto"
          value={form.concepto}
          onChange={(e) => {
            setForm((f) => ({ ...f, concepto: e.target.value as ConceptoAjuste }))
          }}
          options={(Object.keys(CONCEPTO) as ConceptoAjuste[]).map((c) => ({
            value: c,
            label: CONCEPTO[c],
          }))}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Importe"
            inputMode="decimal"
            placeholder="0,02"
            className="[&_input]:tabular-nums"
            value={form.importe}
            error={problem?.fieldErrors.importe}
            onChange={(e) => {
              setForm((f) => ({ ...f, importe: e.target.value }))
            }}
          />
          <Field
            label={pideResolucion ? 'Resolución de la Junta' : 'Resolución (opcional)'}
            placeholder="Acta 12/2026"
            maxLength={120}
            value={form.resolucion}
            error={problem?.fieldErrors.resolucion}
            onChange={(e) => {
              setForm((f) => ({ ...f, resolucion: e.target.value }))
            }}
          />
        </div>
        <TextArea
          label="Justificación"
          value={form.justificacion}
          maxLength={2000}
          hint="Obligatoria, mínimo 10 caracteres. Por qué se ajusta: queda en la auditoría."
          error={problem?.fieldErrors.justificacion}
          onChange={(e) => {
            setForm((f) => ({ ...f, justificacion: e.target.value }))
          }}
        />
      </div>
    </Dialog>
  )
}

const ESTADO_BOLETA: Record<string, { label: string; tone: Tone }> = {
  PENDIENTE: { label: 'Pendiente', tone: 'warning' },
  PAGADA: { label: 'Pagada', tone: 'success' },
  ANULADA: { label: 'Anulada', tone: 'unknown' },
}

function BuscarBoleta({ onRechazar }: { onRechazar: (a: Ajuste) => void }) {
  const { can } = useSession()
  const [texto, setTexto] = useState('')
  const [numero, setNumero] = useState<number | null>(null)
  const [proponiendo, setProponiendo] = useState(false)
  const query = useQuery({
    queryKey: ['ajustes', 'boleta', numero],
    queryFn: () => fetchBoletaParaAjustar(numero ?? 0),
    enabled: numero !== null,
    retry: false,
  })
  const buscar = (e: SyntheticEvent) => {
    e.preventDefault()
    const n = Number.parseInt(texto.replace(/\D/g, ''), 10)
    setNumero(Number.isFinite(n) && n > 0 ? n : null)
  }
  const datos = query.data
  const b = datos?.boleta
  return (
    <Panel
      title="Ajustar una boleta"
      description="Buscá la boleta por su número para ver lo que queda pagar y sus ajustes."
    >
      <form onSubmit={buscar} className="flex flex-wrap items-end gap-3 px-5 py-4 sm:px-6">
        <Field
          label="N° de boleta"
          inputMode="numeric"
          className="w-48 [&_input]:tabular-nums"
          value={texto}
          onChange={(e) => {
            setTexto(e.target.value)
          }}
        />
        <Button type="submit" icon={Search} disabled={!texto.trim()}>
          Buscar
        </Button>
      </form>
      <div aria-live="polite" aria-busy={query.isFetching}>
        {query.isError && (
          <div className="px-5 pb-4 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}
        {datos && b && (
          <div className="border-t border-line">
            <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 px-5 py-4 sm:px-6">
              <div className="min-w-0">
                <p className="font-semibold text-ink">
                  Boleta N° <span className="tabular-nums">{b.numero}</span>
                  {' · '}
                  <Link to={`/ddjj/${b.ddjj_id}`}>{formatPeriodo(b.periodo)}</Link>
                </p>
                <p className="text-sm text-ink-muted">
                  {registroLabel(b.registro)}
                  {datos.escribano && ` · ${datos.escribano}`}
                </p>
              </div>
              <StatusIndicator
                tone={ESTADO_BOLETA[b.estado]?.tone ?? 'unknown'}
                label={ESTADO_BOLETA[b.estado]?.label ?? b.estado}
              />
            </div>
            <dl className="divide-y divide-line border-t border-line">
              <div className="flex justify-between gap-4 px-5 py-3 sm:px-6">
                <dt className="text-sm font-medium text-ink-muted">Total de la boleta</dt>
                <dd className="tabular-nums">{formatMoney(b.total_a_pagar)}</dd>
              </div>
              <div className="flex justify-between gap-4 bg-surface-sunken px-5 py-3 sm:px-6">
                <dt className="text-sm font-semibold text-ink">Queda pagar</dt>
                <dd className="font-semibold text-brand-900 tabular-nums">
                  {formatMoney(b.saldo_a_pagar)}
                </dd>
              </div>
            </dl>
            {b.estado === 'PENDIENTE' && can('ajustes:proponer') && (
              <div className="border-t border-line px-5 py-4 sm:px-6">
                <Button
                  variant="primary"
                  icon={Plus}
                  onClick={() => {
                    setProponiendo(true)
                  }}
                >
                  Proponer crédito o débito
                </Button>
              </div>
            )}
            {datos.ajustes.length > 0 ? (
              <ul className="divide-y divide-line border-t border-line">
                {[...datos.ajustes].reverse().map((a) => (
                  <FilaAjuste key={a.id} a={a} conBoleta={false} onRechazar={onRechazar} />
                ))}
              </ul>
            ) : (
              <p className="border-t border-line px-5 py-4 text-ink-muted sm:px-6">
                Esta boleta no tiene ajustes.
              </p>
            )}
            <ProponerDialog
              datos={datos}
              open={proponiendo}
              onClose={() => {
                setProponiendo(false)
              }}
            />
          </div>
        )}
      </div>
    </Panel>
  )
}

const PAGE_SIZE = 20

export function AjustesPage() {
  const [estado, setEstado] = useState<EstadoAjuste | ''>('PROPUESTO')
  const [page, setPage] = useState(1)
  const [rechazando, setRechazando] = useState<Ajuste | null>(null)
  const lista = useQuery({
    queryKey: ['ajustes', 'lista', estado, page],
    queryFn: () => fetchAjustes({ estado, page, pageSize: PAGE_SIZE }),
  })
  return (
    <>
      <PageHeader
        title="Créditos y débitos"
        description="Para cuadrar la cuenta de un escribano: centavos de más o de menos, una rebaja de intereses o una condonación de la Junta, la diferencia de una rectificativa. Un crédito baja lo que se debe de la boleta y un débito lo sube. Cada ajuste lo aprueba otra persona y nada se borra: un error se corrige con otro ajuste en sentido contrario."
      />
      <div className="grid gap-6">
        <BuscarBoleta onRechazar={setRechazando} />
        <Panel
          title={estado === 'PROPUESTO' ? 'Por aprobar' : 'Ajustes'}
          actions={
            <Select
              label="Estado"
              className="w-44"
              value={estado}
              onChange={(e) => {
                setEstado(e.target.value as EstadoAjuste | '')
                setPage(1)
              }}
              options={[
                { value: 'PROPUESTO', label: 'Por aprobar' },
                { value: 'APROBADO', label: 'Aprobados' },
                { value: 'RECHAZADO', label: 'Rechazados' },
                { value: '', label: 'Todos' },
              ]}
            />
          }
        >
          <div aria-live="polite" aria-busy={lista.isPending}>
            {lista.isPending && (
              <ul className="divide-y divide-line">
                {[0, 1].map((i) => (
                  <li key={i} className="px-5 py-4 sm:px-6">
                    <div className="h-16 animate-pulse rounded-control bg-brand-50" />
                  </li>
                ))}
              </ul>
            )}
            {lista.isError && (
              <div className="px-5 py-4 sm:px-6">
                <Alert tone="danger">{toProblem(lista.error).detail}</Alert>
              </div>
            )}
            {lista.data && lista.data.items.length === 0 && (
              <p className="px-5 py-6 text-ink-muted sm:px-6">
                {estado === 'PROPUESTO'
                  ? 'No hay ajustes esperando aprobación.'
                  : 'No hay ajustes en este estado.'}
              </p>
            )}
            {lista.data && lista.data.items.length > 0 && (
              <ul className="divide-y divide-line">
                {lista.data.items.map((a) => (
                  <FilaAjuste key={a.id} a={a} conBoleta onRechazar={setRechazando} />
                ))}
              </ul>
            )}
          </div>
          {lista.data && lista.data.total > PAGE_SIZE && (
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={lista.data.total}
              onPage={setPage}
            />
          )}
        </Panel>
      </div>
      <RechazarDialog
        ajuste={rechazando}
        onClose={() => {
          setRechazando(null)
        }}
      />
    </>
  )
}
