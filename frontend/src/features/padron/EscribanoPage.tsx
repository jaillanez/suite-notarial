import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  CalendarOff,
  ClipboardPen,
  FilePen,
  Pencil,
  RefreshCw,
  ShieldPlus,
  UserCheck,
  UserPlus,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'

import { StatusIndicator, type Tone } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { useSession } from '../auth/session'
import { PuntosPanel } from '../previsional/PuntosPanel'
import { fetchEscribano, type CargoItem, type EstadoDesignacion, type LicenciaItem } from './api'
import {
  AsignarCargoDialog,
  CerrarCargoDialog,
  FechaDesdeCargoDialog,
  CompletarDatosDialog,
  CuentaDialog,
  EditarEscribanoDialog,
  EstadoDialog,
} from './EscribanoDialogs'
import {
  A_COMPLETAR,
  CAMPO_A_COMPLETAR,
  CARGO,
  ESTADO_MATRICULA,
  aniosMeses,
  formatDate,
} from './labels'
import {
  AnularLicenciaDialog,
  LicenciaNuevaDialog,
  PrimeraEscrituraDialog,
  TerminarLicenciaDialog,
} from './LicenciaDialogs'

const ESTADO_DESIGNACION: Record<EstadoDesignacion, { label: string; tone: Tone }> = {
  PENDIENTE: { label: 'Pendiente', tone: 'warning' },
  APROBADA: { label: 'Aprobada', tone: 'success' },
  RECHAZADA: { label: 'Rechazada', tone: 'unknown' },
  ANULADA: { label: 'Anulada', tone: 'unknown' },
}

/** Dato que no vino del sistema anterior: se ve como pendiente, no como vacío. */
function ACompletar() {
  return <span className="font-semibold text-warning-700">{A_COMPLETAR}</span>
}

function Rows({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="divide-y divide-line">
      {items.map(([label, value]) => (
        <div
          key={label}
          className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 px-5 py-3.5 sm:px-6"
        >
          <dt className="text-sm font-medium text-ink-muted">{label}</dt>
          <dd className="text-right text-ink tabular-nums">{value ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}

type DialogName =
  'editar' | 'estado' | 'cargo' | 'cuenta' | 'completar' | 'primera' | 'licencia' | null

export function EscribanoPage() {
  const { id = '' } = useParams()
  const { can } = useSession()
  const query = useQuery({ queryKey: ['escribano', id], queryFn: () => fetchEscribano(id) })
  const [dialog, setDialog] = useState<DialogName>(null)
  const [cerrando, setCerrando] = useState<CargoItem | null>(null)
  const [fechando, setFechando] = useState<CargoItem | null>(null)
  const [terminando, setTerminando] = useState<LicenciaItem | null>(null)
  const [anulando, setAnulando] = useState<LicenciaItem | null>(null)

  if (query.isPending) {
    return (
      <div aria-busy="true" className="space-y-4">
        <span className="block h-9 w-72 animate-pulse rounded-control bg-brand-50" />
        <span className="block h-48 w-full animate-pulse rounded-panel bg-brand-50" />
      </div>
    )
  }
  if (query.isError) {
    return <Alert tone="danger">{toProblem(query.error).detail}</Alert>
  }

  const e = query.data
  const estado = ESTADO_MATRICULA[e.estado_matricula]
  const vigente = e.cargos.find((c) => c.is_current) ?? null
  const sinTransiciones = e.transiciones_permitidas.length === 0
  const canWrite = can('escribanos:write')

  return (
    <>
      <Link
        to="/padron/escribanos"
        className="mb-6 inline-flex min-h-11 items-center gap-2 text-sm font-semibold no-underline hover:underline"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Padrón de escribanos
      </Link>
      <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-brand-900 sm:text-[1.75rem]">
            {e.apellido_nombre}
          </h1>
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-ink-muted tabular-nums">
            <span>
              {e.matricula_numero === null
                ? 'Matrícula a completar'
                : `Matrícula ${String(e.matricula_numero)}`}
            </span>
            <span aria-hidden="true">·</span>
            <span>{e.cuit === null ? 'CUIT a completar' : `CUIT ${e.cuit}`}</span>
            <StatusIndicator tone={estado.tone} label={estado.label} />
            {e.en_licencia_desde && (
              <StatusIndicator
                tone="warning"
                label={`En licencia desde el ${formatDate(e.en_licencia_desde)}`}
              />
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canWrite && (
            <Button
              icon={Pencil}
              onClick={() => {
                setDialog('editar')
              }}
            >
              Editar datos
            </Button>
          )}
          {can('escribanos:status') && !sinTransiciones && (
            <Button
              icon={RefreshCw}
              onClick={() => {
                setDialog('estado')
              }}
            >
              Cambiar estado
            </Button>
          )}
        </div>
      </div>

      {e.a_completar.length > 0 && (
        <div className="mb-6">
          <Alert
            tone="warning"
            title="Datos a completar"
            action={
              canWrite ? (
                <Button
                  icon={ClipboardPen}
                  onClick={() => {
                    setDialog('completar')
                  }}
                >
                  Completar datos
                </Button>
              ) : undefined
            }
          >
            Falta cargar: {e.a_completar.map((c) => CAMPO_A_COMPLETAR[c].toLowerCase()).join(', ')}.
            {e.a_completar.includes('cuit') && ' Sin CUIT no se le puede crear la cuenta.'}
          </Alert>
        </div>
      )}

      {e.estado_matricula !== 'ACTIVO' && e.motivo_ultimo_cambio_estado && (
        <div className="mb-6">
          <Alert
            tone={estado.tone === 'danger' ? 'danger' : 'warning'}
            title={`Matrícula ${estado.label.toLowerCase()}`}
          >
            {e.motivo_ultimo_cambio_estado}
          </Alert>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Datos personales">
          <Rows
            items={[
              ['Apellido y nombre', `${e.persona.apellido}, ${e.persona.nombre}`],
              ['CUIT', e.persona.cuit ?? <ACompletar />],
              [e.persona.tipo_documento, e.persona.numero_documento ?? <ACompletar />],
              ['Nacimiento', formatDate(e.persona.fecha_nacimiento)],
              ['Correo', e.persona.email],
              ['Teléfono', e.persona.telefono],
              ['Domicilio real', e.persona.domicilio_real],
            ]}
          />
        </Panel>
        <Panel title="Matrícula">
          <Rows
            items={[
              ['Número', e.matricula_numero ?? <ACompletar />],
              ['Tomo / folio', [e.tomo, e.folio].filter(Boolean).join(' / ') || '—'],
              [
                'Fecha de juramento',
                e.fecha_matriculacion ? formatDate(e.fecha_matriculacion) : <ACompletar />,
              ],
              [
                'Cuenta de autogestión',
                e.tiene_cuenta ? (
                  <span className="inline-flex items-center gap-1.5 text-success-700">
                    <UserCheck aria-hidden="true" className="size-4" strokeWidth={2.25} />
                    Creada
                  </span>
                ) : (
                  'Sin cuenta'
                ),
              ],
            ]}
          />
          {!e.tiene_cuenta && can('escribanos:write') && can('users:write') && (
            <div className="space-y-3 border-t border-line px-5 py-4 sm:px-6">
              <Button
                icon={UserPlus}
                disabled={!e.persona.email || e.persona.cuit === null}
                onClick={() => {
                  setDialog('cuenta')
                }}
              >
                Crear cuenta de autogestión
              </Button>
              {e.persona.cuit === null && (
                <p className="text-sm text-ink-muted">
                  Completá su CUIT para poder crearle la cuenta.
                </p>
              )}
              {!e.persona.email && (
                <p className="text-sm text-ink-muted">
                  Cargá su correo en “Editar datos” para poder crearle la cuenta.
                </p>
              )}
            </div>
          )}
        </Panel>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Panel
          title="Primera escritura"
          description="Determina la antigüedad para la jubilación."
          actions={
            canWrite ? (
              <Button
                icon={FilePen}
                onClick={() => {
                  setDialog('primera')
                }}
              >
                {e.primera_escritura ? 'Corregir' : 'Cargar'}
              </Button>
            ) : undefined
          }
        >
          <Rows
            items={
              e.primera_escritura
                ? [
                    ['Fecha', formatDate(e.primera_escritura.fecha)],
                    [
                      'Escritura',
                      `Nº ${e.primera_escritura.numero} · Registro ${String(e.primera_escritura.registro)}${e.primera_escritura.folio ? ` · Folio ${e.primera_escritura.folio}` : ''}`,
                    ],
                    [
                      'Antigüedad (desde la primera escritura)',
                      e.antiguedad ? aniosMeses(e.antiguedad.anios, e.antiguedad.meses) : '—',
                    ],
                  ]
                : [
                    ['Primera escritura', <ACompletar key="pe" />],
                    ['Antigüedad (desde la primera escritura)', <ACompletar key="an" />],
                  ]
            }
          />
        </Panel>

        <Panel
          title="Licencias"
          description="No cambian el estado de la matrícula ni el cargo."
          actions={
            canWrite && !e.en_licencia_desde ? (
              <Button
                icon={CalendarOff}
                onClick={() => {
                  setDialog('licencia')
                }}
              >
                Registrar licencia
              </Button>
            ) : undefined
          }
        >
          {e.licencias.length === 0 ? (
            <p className="px-5 py-6 text-sm text-ink-muted sm:px-6">Nunca tuvo licencias.</p>
          ) : (
            <ol className="divide-y divide-line">
              {e.licencias.map((l) => (
                <li
                  key={l.id}
                  className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-3.5 sm:px-6"
                >
                  <div className="min-w-0">
                    <p
                      className={`tabular-nums ${l.anulada ? 'text-ink-muted line-through' : 'font-semibold text-ink'}`}
                    >
                      {formatDate(l.fecha_desde)} —{' '}
                      {l.fecha_hasta ? formatDate(l.fecha_hasta) : 'sin fecha de regreso'}
                    </p>
                    <p className="max-w-[65ch] text-sm text-ink-muted">
                      {l.motivo}
                      {l.resolucion_respaldo ? ` · ${l.resolucion_respaldo}` : ''}
                    </p>
                    {l.anulada && l.motivo_anulacion && (
                      <p className="text-sm text-ink-muted">Anulada: {l.motivo_anulacion}</p>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {l.vigente && <StatusIndicator tone="warning" label="Vigente" />}
                    {l.anulada && <StatusIndicator tone="unknown" label="Anulada" />}
                    {canWrite && !l.anulada && (
                      <>
                        {(l.fecha_hasta === null || l.vigente) && (
                          <Button
                            onClick={() => {
                              setTerminando(l)
                            }}
                          >
                            Terminar
                          </Button>
                        )}
                        <Button
                          variant="danger"
                          onClick={() => {
                            setAnulando(l)
                          }}
                        >
                          Anular
                        </Button>
                      </>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Panel>
      </div>

      <Panel
        className="mt-6"
        title="Cargos en registros notariales"
        description={
          vigente
            ? `${CARGO[vigente.cargo]} en el Registro ${String(vigente.numero_registro)} ${vigente.fecha_desde ? `desde el ${formatDate(vigente.fecha_desde)}` : '(fecha desde a completar)'}.`
            : 'Sin cargo vigente.'
        }
        actions={
          canWrite && !vigente && e.estado_matricula === 'ACTIVO' ? (
            <Button
              variant="primary"
              icon={ShieldPlus}
              onClick={() => {
                setDialog('cargo')
              }}
            >
              Asignar cargo
            </Button>
          ) : undefined
        }
      >
        {e.cargos.length === 0 ? (
          <p className="px-5 py-6 text-sm text-ink-muted sm:px-6">Nunca tuvo cargos registrados.</p>
        ) : (
          <ul className="divide-y divide-line">
            {e.cargos.map((c) => (
              <li
                key={c.id}
                className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-3.5 sm:px-6"
              >
                <div className="min-w-0">
                  <Link
                    to={`/padron/registros/${c.registro_id}`}
                    className="font-semibold no-underline hover:underline"
                  >
                    {CARGO[c.cargo]} · Registro {c.numero_registro}
                  </Link>
                  <p className="text-sm text-ink-muted tabular-nums">
                    {c.fecha_desde ? formatDate(c.fecha_desde) : <ACompletar />} —{' '}
                    {c.is_current ? 'vigente' : formatDate(c.fecha_hasta)}
                    {c.resolucion_designacion ? ` · ${c.resolucion_designacion}` : ''}
                  </p>
                  {c.motivo_cierre && (
                    <p className="text-sm text-ink-muted">Cierre: {c.motivo_cierre}</p>
                  )}
                </div>
                {canWrite && (c.fecha_desde === null || c.is_current) && (
                  <div className="flex flex-wrap gap-2">
                    {c.fecha_desde === null && (
                      <Button
                        onClick={() => {
                          setFechando(c)
                        }}
                      >
                        Cargar fecha desde
                      </Button>
                    )}
                    {c.is_current && (
                      <Button
                        variant="danger"
                        onClick={() => {
                          setCerrando(c)
                        }}
                      >
                        Cerrar cargo
                      </Button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {e.designaciones_a_cargo.length > 0 && (
        <Panel
          className="mt-6"
          title="A cargo de otros registros"
          description="Designaciones durante la ausencia de un titular. Conviven con su cargo propio."
        >
          <ul className="divide-y divide-line">
            {e.designaciones_a_cargo.map((d) => (
              <li
                key={d.id}
                className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-3.5 sm:px-6"
              >
                <div className="min-w-0">
                  <Link
                    to={`/padron/registros/${d.registro_id}`}
                    className="font-semibold no-underline hover:underline"
                  >
                    Registro {d.numero_registro}
                  </Link>
                  <p className="text-sm text-ink-muted tabular-nums">
                    {formatDate(d.fecha_desde)} — {formatDate(d.fecha_hasta)} · {d.motivo}
                  </p>
                </div>
                <StatusIndicator
                  tone={ESTADO_DESIGNACION[d.estado].tone}
                  label={ESTADO_DESIGNACION[d.estado].label}
                />
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {can('puntos:read_all') && <PuntosPanel className="mt-6" escribanoId={e.id} />}

      <Panel
        className="mt-6"
        title="Historial de estados"
        description="Registro inmutable de cada cambio de estado de la matrícula."
      >
        {e.historial.length === 0 ? (
          <p className="px-5 py-6 text-sm text-ink-muted sm:px-6">
            Sin cambios de estado desde el juramento.
          </p>
        ) : (
          <ol className="divide-y divide-line">
            {e.historial.map((h) => (
              <li key={h.id} className="px-5 py-4 sm:px-6">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusIndicator
                    tone={ESTADO_MATRICULA[h.estado_anterior].tone}
                    label={ESTADO_MATRICULA[h.estado_anterior].label}
                  />
                  <span aria-hidden="true" className="text-ink-subtle">
                    →
                  </span>
                  <span className="sr-only">pasó a</span>
                  <StatusIndicator
                    tone={ESTADO_MATRICULA[h.estado_nuevo].tone}
                    label={ESTADO_MATRICULA[h.estado_nuevo].label}
                  />
                  <span className="text-sm text-ink-muted tabular-nums">
                    desde el {formatDate(h.fecha_efectiva)}
                  </span>
                </div>
                <p className="mt-2 max-w-[65ch] text-ink">{h.motivo}</p>
                <p className="mt-1 text-xs text-ink-muted tabular-nums">
                  {h.resolucion_respaldo ? `${h.resolucion_respaldo} · ` : ''}
                  Registrado el {formatLocalDateTime(new Date(h.fecha_cambio))}
                  {h.operador_email ? ` por ${h.operador_email}` : ''}
                </p>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <EditarEscribanoDialog
        key={`editar-${String(dialog === 'editar')}`}
        escribano={e}
        open={dialog === 'editar'}
        onClose={() => {
          setDialog(null)
        }}
      />
      <EstadoDialog
        key={`estado-${e.estado_matricula}-${String(dialog === 'estado')}`}
        escribano={e}
        open={dialog === 'estado'}
        onClose={() => {
          setDialog(null)
        }}
      />
      <AsignarCargoDialog
        escribano={e}
        open={dialog === 'cargo'}
        onClose={() => {
          setDialog(null)
        }}
      />
      <CompletarDatosDialog
        key={`completar-${e.a_completar.join('-')}-${String(dialog === 'completar')}`}
        escribano={e}
        open={dialog === 'completar'}
        onClose={() => {
          setDialog(null)
        }}
      />
      <CuentaDialog
        escribano={e}
        open={dialog === 'cuenta'}
        onClose={() => {
          setDialog(null)
        }}
      />
      <CerrarCargoDialog
        escribano={e}
        cargo={cerrando}
        onClose={() => {
          setCerrando(null)
        }}
      />
      <FechaDesdeCargoDialog
        escribano={e}
        cargo={fechando}
        onClose={() => {
          setFechando(null)
        }}
      />
      <PrimeraEscrituraDialog
        key={`primera-${String(dialog === 'primera')}`}
        escribano={e}
        open={dialog === 'primera'}
        onClose={() => {
          setDialog(null)
        }}
      />
      <LicenciaNuevaDialog
        key={`licencia-${String(dialog === 'licencia')}`}
        escribano={e}
        open={dialog === 'licencia'}
        onClose={() => {
          setDialog(null)
        }}
      />
      <TerminarLicenciaDialog
        key={`terminar-${terminando?.id ?? ''}`}
        escribano={e}
        licencia={terminando}
        onClose={() => {
          setTerminando(null)
        }}
      />
      <AnularLicenciaDialog
        key={`anular-${anulando?.id ?? ''}`}
        escribano={e}
        licencia={anulando}
        onClose={() => {
          setAnulando(null)
        }}
      />
    </>
  )
}
