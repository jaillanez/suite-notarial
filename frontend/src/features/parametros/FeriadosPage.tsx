import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CalendarX2, Plus, Save } from 'lucide-react'
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
import { useSession } from '../auth/session'
import { formatDate, todayIso } from '../padron/labels'
import { bajaFeriado, crearFeriado, fetchFeriados, type Feriado } from './api'

const DIA_SEMANA = new Intl.DateTimeFormat('es-AR', { weekday: 'long', timeZone: 'UTC' })

function diaSemana(iso: string): string {
  return DIA_SEMANA.format(new Date(`${iso}T00:00:00Z`))
}

function NuevoFeriadoDialog({
  anio,
  open,
  onClose,
}: {
  anio: number
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [fecha, setFecha] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const save = useMutation({
    mutationFn: () => crearFeriado({ fecha, descripcion: descripcion.trim() }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['feriados'] })
      setFecha('')
      setDescripcion('')
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Agregar feriado nacional"
      description="Ese día no se podrán cargar escrituras ni elegir como fecha de pago de una boleta. Los feriados provinciales no se cargan: en ellos los registros autorizan actos."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Guardando…"
            disabled={!fecha || descripcion.trim().length < 3}
            onClick={() => {
              save.mutate()
            }}
          >
            Agregar feriado
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {problem && Object.keys(problem.fieldErrors).length === 0 && (
          <Alert tone="danger">{problem.detail}</Alert>
        )}
        <Field
          label="Fecha"
          type="date"
          min={`${String(anio)}-01-01`}
          max={`${String(anio)}-12-31`}
          value={fecha}
          error={problem?.fieldErrors.fecha}
          onChange={(e) => {
            setFecha(e.target.value)
          }}
        />
        <Field
          label="Descripción"
          placeholder="Día de la Independencia"
          maxLength={200}
          value={descripcion}
          error={problem?.fieldErrors.descripcion}
          hint="Como figura en el calendario oficial."
          onChange={(e) => {
            setDescripcion(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

function BajaFeriadoDialog({ feriado, onClose }: { feriado: Feriado | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [motivo, setMotivo] = useState('')
  const save = useMutation({
    mutationFn: (id: string) => bajaFeriado(id, motivo.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['feriados'] })
      setMotivo('')
      onClose()
    },
  })
  return (
    <Dialog
      open={feriado !== null}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Dar de baja el feriado"
      description={
        feriado
          ? `${formatDate(feriado.fecha)} · ${feriado.descripcion}. Vuelve a ser día hábil. La baja queda en la auditoría y no se borra.`
          : undefined
      }
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="danger"
            busy={save.isPending}
            busyLabel="Dando de baja…"
            disabled={motivo.trim().length < 5}
            onClick={() => {
              if (feriado) save.mutate(feriado.id)
            }}
          >
            Dar de baja
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

export function FeriadosPage() {
  const { can } = useSession()
  const puedeCargar = can('parameters:write')
  const actual = Number(todayIso().slice(0, 4))
  const [anio, setAnio] = useState(actual)
  const [nuevo, setNuevo] = useState(false)
  const [baja, setBaja] = useState<Feriado | null>(null)
  const feriados = useQuery({
    queryKey: ['feriados', anio],
    queryFn: () => fetchFeriados(anio),
  })
  const items = feriados.data ?? []
  const vigentes = items.filter((f) => f.is_active).length
  const anios = [actual - 1, actual, actual + 1]
  return (
    <>
      <Link
        to="/parametros"
        className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-medium"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Parámetros
      </Link>
      <PageHeader
        title="Feriados nacionales"
        description="Días en que no se autorizan escrituras ni se acreditan pagos, además de sábados y domingos. La Caja carga el calendario oficial de cada año; los feriados provinciales no se cargan."
      />
      <Panel
        title={`Calendario ${String(anio)}`}
        description={
          feriados.isSuccess
            ? vigentes === 1
              ? '1 feriado vigente.'
              : `${String(vigentes)} feriados vigentes.`
            : undefined
        }
        actions={
          <>
            <Select
              label="Año"
              className="w-32"
              value={String(anio)}
              onChange={(e) => {
                setAnio(Number(e.target.value))
              }}
              options={anios.map((a) => ({ value: String(a), label: String(a) }))}
            />
            {puedeCargar && (
              <Button
                variant="primary"
                icon={Plus}
                className="self-end"
                onClick={() => {
                  setNuevo(true)
                }}
              >
                Agregar feriado
              </Button>
            )}
          </>
        }
        footer="Cada alta y baja queda en la auditoría. Un feriado dado de baja no se borra."
      >
        <div aria-live="polite" aria-busy={feriados.isPending}>
          {feriados.isPending && (
            <ul className="divide-y divide-line">
              {[0, 1, 2].map((i) => (
                <li key={i} className="px-5 py-4 sm:px-6">
                  <div className="h-11 animate-pulse rounded-control bg-brand-50" />
                </li>
              ))}
            </ul>
          )}
          {feriados.isError && (
            <div className="px-5 py-4 sm:px-6">
              <Alert tone="danger">{toProblem(feriados.error).detail}</Alert>
            </div>
          )}
          {feriados.isSuccess && items.length === 0 && (
            <div className="flex items-start gap-3 px-5 py-6 text-ink-muted sm:px-6">
              <CalendarX2
                aria-hidden="true"
                className="mt-0.5 size-5 shrink-0"
                strokeWidth={2.25}
              />
              <p className="max-w-[65ch]">
                Todavía no hay feriados cargados para {anio}. Mientras tanto, solo se bloquean
                sábados y domingos.
                {puedeCargar && ' Cargalos con «Agregar feriado».'}
              </p>
            </div>
          )}
          {items.length > 0 && (
            <ul className="divide-y divide-line">
              {items.map((f) => (
                <li
                  key={f.id}
                  className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-5 py-4 sm:px-6"
                >
                  <div className="min-w-0">
                    <p className="font-semibold text-ink tabular-nums">
                      {formatDate(f.fecha)}{' '}
                      <span className="font-normal text-ink-muted">· {diaSemana(f.fecha)}</span>
                    </p>
                    <p className={f.is_active ? 'text-ink' : 'text-ink-muted line-through'}>
                      {f.descripcion}
                    </p>
                    {!f.is_active && f.baja_motivo && (
                      <p className="mt-1 text-sm text-ink-muted">Baja: {f.baja_motivo}</p>
                    )}
                  </div>
                  {f.is_active ? (
                    puedeCargar && (
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setBaja(f)
                        }}
                      >
                        Dar de baja
                      </Button>
                    )
                  ) : (
                    <StatusIndicator tone="unknown" label="Dado de baja" />
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Panel>
      {puedeCargar && (
        <NuevoFeriadoDialog
          anio={anio}
          open={nuevo}
          onClose={() => {
            setNuevo(false)
          }}
        />
      )}
      <BajaFeriadoDialog
        feriado={baja}
        onClose={() => {
          setBaja(null)
        }}
      />
    </>
  )
}
