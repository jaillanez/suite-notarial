import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Pencil, RefreshCw, ShieldPlus, UserCheck, UserPlus } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { useSession } from '../auth/session'
import { fetchEscribano, type CargoItem } from './api'
import {
  AsignarCargoDialog,
  CerrarCargoDialog,
  CuentaDialog,
  EditarEscribanoDialog,
  EstadoDialog,
} from './EscribanoDialogs'
import { CARGO, ESTADO_MATRICULA, formatDate } from './labels'

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

type DialogName = 'editar' | 'estado' | 'cargo' | 'cuenta' | null

export function EscribanoPage() {
  const { id = '' } = useParams()
  const { can } = useSession()
  const query = useQuery({ queryKey: ['escribano', id], queryFn: () => fetchEscribano(id) })
  const [dialog, setDialog] = useState<DialogName>(null)
  const [cerrando, setCerrando] = useState<CargoItem | null>(null)

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
            <span>Matrícula {e.matricula_numero}</span>
            <span aria-hidden="true">·</span>
            <span>CUIT {e.cuit}</span>
            <StatusIndicator tone={estado.tone} label={estado.label} />
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
              ['CUIT', e.persona.cuit],
              [e.persona.tipo_documento, e.persona.numero_documento],
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
              ['Número', e.matricula_numero],
              ['Tomo / folio', [e.tomo, e.folio].filter(Boolean).join(' / ') || '—'],
              ['Matriculación', formatDate(e.fecha_matriculacion)],
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
                disabled={!e.persona.email}
                onClick={() => {
                  setDialog('cuenta')
                }}
              >
                Crear cuenta de autogestión
              </Button>
              {!e.persona.email && (
                <p className="text-sm text-ink-muted">
                  Cargá su correo en “Editar datos” para poder crearle la cuenta.
                </p>
              )}
            </div>
          )}
        </Panel>
      </div>

      <Panel
        className="mt-6"
        title="Cargos en registros notariales"
        description={
          vigente
            ? `${CARGO[vigente.cargo]} en el Registro ${String(vigente.numero_registro)} desde el ${formatDate(vigente.fecha_desde)}.`
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
                    {formatDate(c.fecha_desde)} —{' '}
                    {c.is_current ? 'vigente' : formatDate(c.fecha_hasta)}
                    {c.resolucion_designacion ? ` · ${c.resolucion_designacion}` : ''}
                  </p>
                  {c.motivo_cierre && (
                    <p className="text-sm text-ink-muted">Cierre: {c.motivo_cierre}</p>
                  )}
                </div>
                {c.is_current && canWrite && (
                  <Button
                    variant="danger"
                    onClick={() => {
                      setCerrando(c)
                    }}
                  >
                    Cerrar cargo
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        className="mt-6"
        title="Historial de estados"
        description="Registro inmutable de cada cambio de estado de la matrícula."
      >
        {e.historial.length === 0 ? (
          <p className="px-5 py-6 text-sm text-ink-muted sm:px-6">
            Sin cambios de estado desde la matriculación.
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
    </>
  )
}
