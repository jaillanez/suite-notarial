import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, CalendarCheck, CalendarX2, Check, Search, UserPlus, X } from 'lucide-react'
import { useState } from 'react'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { Pagination } from '../../components/ui/Pagination'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { formatDate, todayIso } from '../padron/labels'
import {
  anular,
  aprobar,
  buscarElegibles,
  designar,
  fetchAjustes,
  fetchDesignaciones,
  fetchRegistrosGestionables,
  fijarAjustes,
  rechazar,
  terminar,
  type Designacion,
  type EstadoDesignacion,
} from './api'
import { situacion } from './labels'

const PAGE_SIZE = 25

const ESTADO_FILTRO: Record<EstadoDesignacion, string> = {
  PENDIENTE: 'Esperan aprobación',
  APROBADA: 'Aprobadas',
  RECHAZADA: 'Rechazadas',
  ANULADA: 'Anuladas',
}

function useActualizar() {
  const client = useQueryClient()
  return async () => {
    await client.invalidateQueries({ queryKey: ['a-cargo'] })
    // Cambia qué registros opera cada escribano.
    await client.invalidateQueries({ queryKey: ['ddjj'] })
  }
}

export function ACargoPage() {
  const [estado, setEstado] = useState<EstadoDesignacion | ''>('')
  const [page, setPage] = useState(1)
  const [nueva, setNueva] = useState(false)
  const hoy = todayIso()
  const ajustes = useQuery({ queryKey: ['a-cargo', 'ajustes'], queryFn: fetchAjustes })
  const registros = useQuery({
    queryKey: ['a-cargo', 'registros'],
    queryFn: fetchRegistrosGestionables,
  })
  const lista = useQuery({
    queryKey: ['a-cargo', 'lista', estado, page],
    queryFn: () => fetchDesignaciones({ page, pageSize: PAGE_SIZE, estado }),
  })
  const personal = ajustes.data?.puede_editar ?? false
  const puedeDesignar = (registros.data?.length ?? 0) > 0

  return (
    <>
      <PageHeader
        title="Escribano a cargo"
        description={
          personal
            ? 'Quién queda a cargo de cada registro y entre qué fechas. Cualquier escribano activo de la provincia puede quedar a cargo, aunque tenga su propio registro.'
            : 'Designá a otro escribano para que quede a cargo de tu registro entre dos fechas (licencia, viaje). En esos días carga y presenta las declaraciones juradas del registro.'
        }
      />
      <div className="space-y-6">
        {ajustes.data && (
          <AjustePanel requiere={ajustes.data.a_cargo_requiere_aprobacion} personal={personal} />
        )}
        <Panel
          title="Designaciones"
          actions={
            puedeDesignar && (
              <Button
                variant="primary"
                icon={UserPlus}
                onClick={() => {
                  setNueva(true)
                }}
              >
                Designar escribano a cargo
              </Button>
            )
          }
        >
          <div className="grid gap-4 border-b border-line px-5 py-4 sm:grid-cols-2 sm:px-6">
            <Select
              label="Estado"
              value={estado}
              onChange={(e) => {
                setEstado(e.target.value as EstadoDesignacion | '')
                setPage(1)
              }}
              options={[
                { value: '', label: 'Todas' },
                ...Object.entries(ESTADO_FILTRO).map(([value, label]) => ({ value, label })),
              ]}
            />
          </div>
          {lista.isError && (
            <div className="px-5 py-4 sm:px-6">
              <Alert tone="danger">{toProblem(lista.error).detail}</Alert>
            </div>
          )}
          <ul className="divide-y divide-line" aria-busy={lista.isFetching}>
            {lista.data?.items.length === 0 && (
              <li className="px-5 py-10 text-center text-ink-muted sm:px-6">
                {estado ? 'Ninguna designación en este estado.' : 'Todavía no hay designaciones.'}
              </li>
            )}
            {lista.data?.items.map((d) => (
              <Fila key={d.id} d={d} hoy={hoy} personal={personal} />
            ))}
          </ul>
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
      {nueva && registros.data && (
        <DesignarDialog
          registros={registros.data}
          requiere={!personal && (ajustes.data?.a_cargo_requiere_aprobacion ?? false)}
          onClose={() => {
            setNueva(false)
          }}
        />
      )}
    </>
  )
}

function AjustePanel({ requiere, personal }: { requiere: boolean; personal: boolean }) {
  const actualizar = useActualizar()
  const cambio = useMutation({
    mutationFn: fijarAjustes,
    onSuccess: actualizar,
  })
  if (!personal) {
    return (
      <Alert tone="info">
        {requiere
          ? 'La designación que cargues espera la aprobación de la Caja: hasta entonces, el escribano designado no opera el registro.'
          : 'La designación rige desde que la cargás, entre sus fechas. La Caja queda avisada.'}
      </Alert>
    )
  }
  const opcion = (valor: boolean, titulo: string, detalle: string) => (
    <label className="flex min-h-11 flex-1 cursor-pointer items-start gap-3 rounded-control border border-line-strong px-4 py-3 has-checked:border-brand-700 has-checked:bg-brand-50">
      <input
        type="radio"
        name="aprobacion-a-cargo"
        className="mt-1 size-4 accent-brand-800"
        checked={requiere === valor}
        disabled={cambio.isPending}
        onChange={() => {
          cambio.mutate(valor)
        }}
      />
      <span>
        <span className="block font-semibold text-ink">{titulo}</span>
        <span className="block text-sm text-ink-muted">{detalle}</span>
      </span>
    </label>
  )
  return (
    <Panel
      title="Designaciones que carga el titular"
      description="Las que carga el personal de la Caja rigen siempre al cargarlas."
    >
      <fieldset className="px-5 py-4 sm:px-6">
        <legend className="sr-only">Aprobación de la Caja</legend>
        {cambio.isError && (
          <div className="mb-4">
            <Alert tone="danger">{toProblem(cambio.error).detail}</Alert>
          </div>
        )}
        <div className="flex flex-col gap-3 sm:flex-row">
          {opcion(
            false,
            'Alcanza con avisar',
            'Rige desde que el titular la carga; la Caja la ve en esta lista.',
          )}
          {opcion(
            true,
            'Aprueba la Caja',
            'Espera la aprobación de otra persona de la Caja antes de regir.',
          )}
        </div>
      </fieldset>
    </Panel>
  )
}

type Accion = 'rechazar' | 'anular' | 'terminar' | null

function Fila({ d, hoy, personal }: { d: Designacion; hoy: string; personal: boolean }) {
  const actualizar = useActualizar()
  const [accion, setAccion] = useState<Accion>(null)
  const aprobacion = useMutation({ mutationFn: () => aprobar(d.id), onSuccess: actualizar })
  const s = situacion(d, hoy)
  return (
    <li className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start sm:px-6">
      <span className="w-20 shrink-0 text-sm text-ink-muted">
        Registro
        <span className="block text-xl font-semibold text-brand-900 tabular-nums">
          {d.numero_registro}
        </span>
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-ink">
          {d.apellido_nombre}{' '}
          <span className="font-normal text-ink-muted tabular-nums">
            · Mat. {d.matricula_numero}
          </span>
        </p>
        <p className="text-sm text-ink tabular-nums">
          Del {formatDate(d.fecha_desde)} al {formatDate(d.fecha_hasta)} · {d.departamento}
        </p>
        <p className="text-sm text-ink-muted">{d.motivo}</p>
        {d.motivo_resolucion && (
          <p className="text-sm text-ink-muted">
            {d.estado === 'RECHAZADA' ? 'Rechazo' : 'Motivo'}: {d.motivo_resolucion}
          </p>
        )}
        {personal && d.cargada_por && (
          <p className="text-xs text-ink-subtle">
            Cargada por {d.cargada_por}
            {d.resuelta_por && d.estado !== 'PENDIENTE' && ` · resuelta por ${d.resuelta_por}`}
          </p>
        )}
        {aprobacion.isError && (
          <div className="mt-2">
            <Alert tone="danger">{toProblem(aprobacion.error).detail}</Alert>
          </div>
        )}
        {(d.puede_aprobar || d.puede_anular || d.puede_terminar) && (
          <div className="mt-3 flex flex-wrap gap-2">
            {d.puede_aprobar && (
              <>
                <Button
                  variant="primary"
                  icon={Check}
                  busy={aprobacion.isPending}
                  busyLabel="Aprobando…"
                  onClick={() => {
                    aprobacion.mutate()
                  }}
                >
                  Aprobar
                </Button>
                <Button
                  icon={X}
                  onClick={() => {
                    setAccion('rechazar')
                  }}
                >
                  Rechazar
                </Button>
              </>
            )}
            {d.puede_terminar && (
              <Button
                icon={CalendarX2}
                onClick={() => {
                  setAccion('terminar')
                }}
              >
                Terminar antes
              </Button>
            )}
            {d.puede_anular && (
              <Button
                icon={Ban}
                onClick={() => {
                  setAccion('anular')
                }}
              >
                Anular
              </Button>
            )}
          </div>
        )}
      </div>
      <StatusIndicator tone={s.tone} label={s.label} />
      {accion && (
        <BajaDialog
          d={d}
          accion={accion}
          onClose={() => {
            setAccion(null)
          }}
        />
      )}
    </li>
  )
}

const BAJA: Record<Exclude<Accion, null>, { titulo: string; boton: string; ayuda: string }> = {
  rechazar: {
    titulo: 'Rechazar la designación',
    boton: 'Rechazar',
    ayuda: 'El titular ve el motivo y puede cargar otra.',
  },
  anular: {
    titulo: 'Anular la designación',
    boton: 'Anular',
    ayuda:
      'Queda sin efecto. Si el escribano a cargo ya declaró actos en esas fechas, terminala antes en lugar de anularla.',
  },
  terminar: {
    titulo: 'Terminar antes',
    boton: 'Terminar',
    ayuda:
      'El escribano a cargo deja de operar el registro después de la nueva fecha. No puede ser anterior a un acto que ya declaró.',
  },
}

function BajaDialog({
  d,
  accion,
  onClose,
}: {
  d: Designacion
  accion: Exclude<Accion, null>
  onClose: () => void
}) {
  const actualizar = useActualizar()
  const [motivo, setMotivo] = useState('')
  const maximo = d.fecha_hasta > d.fecha_desde ? diaAnterior(d.fecha_hasta) : d.fecha_desde
  const [fecha, setFecha] = useState(
    todayIso() < maximo ? maxIso(todayIso(), d.fecha_desde) : maximo,
  )
  const textos = BAJA[accion]
  const baja = useMutation({
    mutationFn: () => {
      const texto = motivo.trim()
      if (accion === 'rechazar') return rechazar(d.id, texto)
      if (accion === 'anular') return anular(d.id, texto)
      return terminar(d.id, fecha, texto)
    },
    onSuccess: async () => {
      await actualizar()
      onClose()
    },
  })
  const problem = baja.isError ? toProblem(baja.error) : null
  return (
    <Dialog
      open
      onClose={onClose}
      title={textos.titulo}
      description={`${d.apellido_nombre}, a cargo del Registro ${String(d.numero_registro)} del ${formatDate(d.fecha_desde)} al ${formatDate(d.fecha_hasta)}.`}
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={accion === 'terminar' ? CalendarCheck : accion === 'anular' ? Ban : X}
            busy={baja.isPending}
            busyLabel="Guardando…"
            disabled={motivo.trim().length < 5 || (accion === 'terminar' && !fecha)}
            onClick={() => {
              baja.mutate()
            }}
          >
            {textos.boton}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">{textos.ayuda}</p>
        {problem && <Alert tone="danger">{problem.detail}</Alert>}
        {accion === 'terminar' && (
          <Field
            label="Nueva fecha hasta"
            type="date"
            className="[&_input]:tabular-nums"
            min={d.fecha_desde}
            max={maximo}
            value={fecha}
            onChange={(e) => {
              setFecha(e.target.value)
            }}
            error={problem?.fieldErrors.fecha_hasta}
          />
        )}
        <TextArea
          label="Motivo"
          hint="Al menos 5 caracteres. Queda en la auditoría."
          rows={3}
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
          error={problem?.fieldErrors.motivo}
        />
      </div>
    </Dialog>
  )
}

function diaAnterior(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() - 1)
  return d.toISOString().slice(0, 10)
}

function maxIso(a: string, b: string): string {
  return a > b ? a : b
}

function DesignarDialog({
  registros,
  requiere,
  onClose,
}: {
  registros: { id: string; numero_registro: number; departamento: string }[]
  requiere: boolean
  onClose: () => void
}) {
  const actualizar = useActualizar()
  const [registroId, setRegistroId] = useState(registros[0]?.id ?? '')
  const [busqueda, setBusqueda] = useState('')
  const [elegido, setElegido] = useState<{ id: string; nombre: string } | null>(null)
  const [desde, setDesde] = useState(todayIso())
  const [hasta, setHasta] = useState('')
  const [motivo, setMotivo] = useState('')
  const termino = busqueda.trim()
  const candidatos = useQuery({
    queryKey: ['a-cargo', 'elegibles', termino],
    queryFn: () => buscarElegibles(termino),
    enabled: termino.length >= 2 && elegido === null,
  })
  const alta = useMutation({
    mutationFn: () =>
      designar({
        registro_id: registroId,
        escribano_id: elegido?.id ?? '',
        fecha_desde: desde,
        fecha_hasta: hasta,
        motivo: motivo.trim(),
      }),
    onSuccess: async () => {
      await actualizar()
      onClose()
    },
  })
  const problem = alta.isError ? toProblem(alta.error) : null
  const listo =
    registroId && elegido && desde && hasta && hasta >= desde && motivo.trim().length >= 5
  return (
    <Dialog
      open
      onClose={onClose}
      title="Designar escribano a cargo"
      description={
        requiere
          ? 'Queda pendiente hasta que la apruebe la Caja.'
          : 'Rige entre las fechas que indiques; la Caja queda avisada.'
      }
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={UserPlus}
            busy={alta.isPending}
            busyLabel="Designando…"
            disabled={!listo}
            onClick={() => {
              alta.mutate()
            }}
          >
            Designar
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {problem && <Alert tone="danger">{problem.detail}</Alert>}
        {registros.length > 1 ? (
          <Select
            label="Registro notarial"
            value={registroId}
            onChange={(e) => {
              setRegistroId(e.target.value)
            }}
            options={registros.map((r) => ({
              value: r.id,
              label: `Nº ${String(r.numero_registro)} · ${r.departamento}`,
            }))}
          />
        ) : (
          <p className="text-sm text-ink">
            Registro Nº{' '}
            <span className="font-semibold tabular-nums">{registros[0]?.numero_registro}</span> ·{' '}
            {registros[0]?.departamento}
          </p>
        )}
        {elegido ? (
          <div className="flex items-center justify-between gap-3 rounded-control border border-line-strong bg-brand-50 px-4 py-3">
            <span>
              <span className="block text-sm text-ink-muted">Queda a cargo</span>
              <span className="font-semibold text-ink">{elegido.nombre}</span>
            </span>
            <Button
              onClick={() => {
                setElegido(null)
              }}
            >
              Cambiar
            </Button>
          </div>
        ) : (
          <div>
            <Field
              label="Escribano que queda a cargo"
              hint="Apellido o número de matrícula. Puede ser de cualquier departamento."
              value={busqueda}
              trailing={<Search aria-hidden="true" className="size-4 text-ink-subtle" />}
              onChange={(e) => {
                setBusqueda(e.target.value)
              }}
            />
            {candidatos.data && (
              <ul className="mt-2 divide-y divide-line rounded-control border border-line">
                {candidatos.data.length === 0 && (
                  <li className="px-4 py-3 text-sm text-ink-muted">
                    Ningún escribano activo coincide.
                  </li>
                )}
                {candidatos.data.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      className="flex min-h-11 w-full cursor-pointer flex-col items-start px-4 py-2 text-left hover:bg-brand-50"
                      onClick={() => {
                        setElegido({
                          id: c.id,
                          nombre: `${c.apellido_nombre} · Mat. ${String(c.matricula_numero)}`,
                        })
                      }}
                    >
                      <span className="font-semibold text-brand-800">{c.apellido_nombre}</span>
                      <span className="text-sm text-ink-muted tabular-nums">
                        Mat. {c.matricula_numero}
                        {c.numero_registro !== null &&
                          ` · Registro ${String(c.numero_registro)} (${c.departamento ?? ''})`}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Desde"
            type="date"
            className="[&_input]:tabular-nums"
            value={desde}
            onChange={(e) => {
              setDesde(e.target.value)
            }}
            error={problem?.fieldErrors.fecha_desde}
          />
          <Field
            label="Hasta"
            type="date"
            className="[&_input]:tabular-nums"
            min={desde}
            value={hasta}
            onChange={(e) => {
              setHasta(e.target.value)
            }}
            error={problem?.fieldErrors.fecha_hasta}
          />
        </div>
        <TextArea
          label="Motivo"
          hint="Por ejemplo: licencia del titular del 1 al 31 de octubre."
          rows={2}
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
          error={problem?.fieldErrors.motivo}
        />
      </div>
    </Dialog>
  )
}
