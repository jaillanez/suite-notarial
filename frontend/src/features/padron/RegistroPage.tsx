import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Lock, Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { useSession } from '../auth/session'
import { fetchRegistro } from './api'
import { CARGO, ESTADO_MATRICULA, ESTADO_REGISTRO, formatDate } from './labels'
import { CerrarRegistroDialog, RegistroFormDialog } from './RegistroDialogs'

export function RegistroPage() {
  const { id = '' } = useParams()
  const { can } = useSession()
  const query = useQuery({ queryKey: ['registro', id], queryFn: () => fetchRegistro(id) })
  const [dialog, setDialog] = useState<'editar' | 'cerrar' | null>(null)

  if (query.isPending) {
    return <span className="block h-48 w-full animate-pulse rounded-panel bg-brand-50" />
  }
  if (query.isError) return <Alert tone="danger">{toProblem(query.error).detail}</Alert>

  const r = query.data
  const estado = ESTADO_REGISTRO[r.estado]
  const cerrado = r.estado === 'CERRADO'
  const canWrite = can('escribanos:write') && !cerrado
  const rows: [string, string][] = [
    ['Circunscripción', r.circunscripcion.nombre],
    ['Departamento', r.departamento],
    ['Domicilio legal', r.domicilio_legal],
    ['Teléfono', r.telefono ?? '—'],
    ['Correo', r.email ?? '—'],
    ['Creación', formatDate(r.fecha_creacion)],
  ]

  return (
    <>
      <Link
        to="/padron/registros"
        className="mb-6 inline-flex min-h-11 items-center gap-2 text-sm font-semibold no-underline hover:underline"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Registros notariales
      </Link>
      <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-brand-900 sm:text-[1.75rem]">
            Registro {r.numero_registro}
            {r.nombre_fantasia ? ` · ${r.nombre_fantasia}` : ''}
          </h1>
          <p className="mt-2">
            <StatusIndicator tone={estado.tone} label={estado.label} />
          </p>
        </div>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            <Button
              icon={Pencil}
              onClick={() => {
                setDialog('editar')
              }}
            >
              Editar
            </Button>
            <Button
              variant="danger"
              icon={Lock}
              onClick={() => {
                setDialog('cerrar')
              }}
            >
              Cerrar registro
            </Button>
          </div>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
        <Panel title="Datos del registro">
          <dl className="divide-y divide-line">
            {rows.map(([label, value]) => (
              <div
                key={label}
                className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 px-5 py-3.5 sm:px-6"
              >
                <dt className="text-sm font-medium text-ink-muted">{label}</dt>
                <dd className="text-right text-ink tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
        </Panel>
        <Panel
          title="Escribanos con cargo vigente"
          description={
            r.titular
              ? undefined
              : 'Registro vacante: asigná el titular desde la ficha del escribano.'
          }
        >
          {r.cargos_vigentes.length === 0 ? (
            <p className="px-5 py-6 text-sm text-ink-muted sm:px-6">Sin cargos vigentes.</p>
          ) : (
            <ul className="divide-y divide-line">
              {r.cargos_vigentes.map((c) => (
                <li key={c.adscripcion_id}>
                  <Link
                    to={`/padron/escribanos/${c.escribano_id}`}
                    className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 text-ink no-underline hover:bg-brand-50 sm:px-6"
                  >
                    <span className="min-w-0">
                      <span className="block font-semibold text-brand-800">
                        {c.apellido_nombre}
                      </span>
                      <span className="block text-sm text-ink-muted tabular-nums">
                        {CARGO[c.cargo]} desde el {formatDate(c.fecha_desde)} · Mat.{' '}
                        {c.matricula_numero}
                      </span>
                    </span>
                    {c.estado_matricula !== 'ACTIVO' && (
                      <StatusIndicator
                        tone={ESTADO_MATRICULA[c.estado_matricula].tone}
                        label={ESTADO_MATRICULA[c.estado_matricula].label}
                      />
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <RegistroFormDialog
        key={`editar-${String(dialog === 'editar')}`}
        registro={r}
        open={dialog === 'editar'}
        onClose={() => {
          setDialog(null)
        }}
      />
      <CerrarRegistroDialog
        registro={r}
        open={dialog === 'cerrar'}
        onClose={() => {
          setDialog(null)
        }}
      />
    </>
  )
}
