import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Calculator, Link2, Search, TableProperties, Unlink } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { Link } from 'react-router'

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
import { formatMoney } from '../../lib/decimal'
import { useSession } from '../auth/session'
import { EscribanoPicker } from '../prestamos/componentes'
import {
  fetchEstadoCalculo,
  fetchSinVincular,
  rechazarSugerencia,
  vincular,
  type EstadoVinculo,
  type SinVincular,
} from './api'
import { formatPuntos } from './labels'

const PAGE_SIZE = 20

function anios(item: SinVincular): string {
  const rango =
    item.primer_anio === item.ultimo_anio
      ? `Ejercicio ${String(item.primer_anio)}`
      : `Ejercicios ${String(item.primer_anio)} a ${String(item.ultimo_anio)}`
  return `${rango} · ${String(item.ejercicios)} con datos`
}

export function VincularDialog({
  item,
  onClose,
}: {
  item: SinVincular | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [escribano, setEscribano] = useState('')
  const [motivo, setMotivo] = useState('')
  // APROXIMADA: sugerencia sin vínculo (no cuenta). HEREDADA: ya cuenta, falta confirmarla.
  const propuesto = item?.escribano ?? null
  const heredada = item?.estado === 'HEREDADA'
  const elegido = escribano || propuesto?.id || ''
  const save = useMutation({
    mutationFn: () =>
      vincular({
        nombre_origen: item?.nombre_origen ?? '',
        escribano_id: elegido,
        motivo: motivo.trim() || null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['previsional'] })
      setEscribano('')
      setMotivo('')
      onClose()
    },
  })
  const rechazar = useMutation({
    mutationFn: () =>
      rechazarSugerencia({ nombre_origen: item?.nombre_origen ?? '', motivo: motivo.trim() }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['previsional'] })
      setMotivo('')
      onClose()
    },
  })
  const cerrar = () => {
    save.reset()
    rechazar.reset()
    setEscribano('')
    setMotivo('')
    onClose()
  }
  return (
    <Dialog
      open={item !== null}
      onClose={cerrar}
      title={propuesto ? 'Revisar vínculo' : 'Vincular con un escribano'}
      description="Todas las filas de este nombre pasan al escribano elegido. Queda auditado."
      footer={
        <>
          <Button onClick={cerrar}>Cancelar</Button>
          {propuesto && !heredada && !escribano && (
            <Button
              variant="danger"
              icon={Unlink}
              disabled={motivo.trim().length < 5}
              busy={rechazar.isPending}
              busyLabel="Rechazando…"
              onClick={() => {
                rechazar.mutate()
              }}
            >
              Rechazar sugerencia
            </Button>
          )}
          <Button
            variant="primary"
            icon={Link2}
            disabled={!elegido}
            busy={save.isPending}
            busyLabel="Vinculando…"
            onClick={() => {
              save.mutate()
            }}
          >
            {propuesto && !escribano ? 'Confirmar vínculo' : 'Vincular'}
          </Button>
        </>
      }
    >
      {item && (
        <div className="space-y-5">
          <dl className="rounded-control border border-line bg-surface-sunken px-4 py-3 text-sm tabular-nums">
            <dt className="text-ink-muted">Nombre en la planilla</dt>
            <dd className="font-semibold text-ink">{item.nombre_origen}</dd>
            <dd className="mt-1 text-ink-muted">
              {anios(item)} · {formatMoney(item.total_aportes)} · {formatPuntos(item.total_puntos)}{' '}
              puntos
            </dd>
            {propuesto && (
              <>
                <dt className="mt-3 text-ink-muted">
                  {heredada ? 'Ya cuenta para' : 'Escribano sugerido (todavía no le cuenta)'}
                </dt>
                <dd className="font-semibold text-ink">
                  {propuesto.apellido_nombre} · Mat. {propuesto.matricula_numero}
                </dd>
              </>
            )}
          </dl>
          <EscribanoPicker
            label={propuesto ? 'Otro escribano (si el propuesto no es)' : 'Escribano'}
            value={escribano}
            opcional={propuesto !== null}
            onChange={setEscribano}
          />
          <TextArea
            label="Motivo"
            hint="Obligatorio para rechazar la sugerencia o si estos puntos ya contaban para otra persona."
            maxLength={1000}
            value={motivo}
            onChange={(e) => {
              setMotivo(e.target.value)
            }}
          />
          {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
          {rechazar.isError && <Alert tone="danger">{toProblem(rechazar.error).detail}</Alert>}
        </div>
      )}
    </Dialog>
  )
}

function SinVincularPanel() {
  const { can } = useSession()
  const [estado, setEstado] = useState<EstadoVinculo>('SIN_VINCULAR')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [abierto, setAbierto] = useState<SinVincular | null>(null)
  const busqueda = useDeferredValue(q)
  const query = useQuery({
    queryKey: ['previsional', 'sin-vincular', estado, busqueda, page],
    queryFn: () => fetchSinVincular(estado, busqueda, page, PAGE_SIZE),
    placeholderData: keepPreviousData,
  })
  const puedeVincular = can('puntos:manage')
  const aRevisar = estado !== 'SIN_VINCULAR'

  return (
    <Panel
      title="Puntos sin vincular"
      description="Nombres de la planilla histórica que no se pudieron asociar con seguridad a un escribano del padrón. Mientras no se vinculen, no figuran en el informe de nadie."
    >
      <div className="grid gap-4 border-b border-line px-5 py-4 sm:grid-cols-2 sm:px-6">
        <Select
          label="Mostrar"
          value={estado}
          onChange={(e) => {
            setEstado(e.target.value as EstadoVinculo)
            setPage(1)
          }}
          options={[
            { value: 'SIN_VINCULAR', label: 'Sin escribano' },
            { value: 'APROXIMADA', label: 'Sugerencias aproximadas a revisar' },
            { value: 'HEREDADA', label: 'Heredados de un vínculo manual, a confirmar' },
          ]}
        />
        <Field
          label="Buscar en la planilla"
          type="search"
          placeholder="Apellido o nombre"
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setPage(1)
          }}
          trailing={
            <Search aria-hidden="true" className="mr-3 size-4 text-ink-subtle" strokeWidth={2.25} />
          }
        />
      </div>
      <div aria-live="polite" aria-busy={query.isFetching}>
        {query.isPending && (
          <div className="space-y-2 px-5 py-5 sm:px-6">
            <span className="block h-12 w-full animate-pulse rounded-control bg-brand-50" />
            <span className="block h-12 w-full animate-pulse rounded-control bg-brand-50" />
          </div>
        )}
        {query.isError && (
          <div className="px-5 py-5 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}
        {query.data && query.data.items.length === 0 && (
          <p className="px-5 py-6 text-sm text-ink-muted sm:px-6">
            {busqueda.trim()
              ? 'Ningún nombre coincide con la búsqueda.'
              : estado === 'HEREDADA'
                ? 'No hay puntos heredados pendientes de confirmar.'
                : aRevisar
                  ? 'No hay sugerencias aproximadas pendientes de revisión.'
                  : 'Todos los puntos cargados están vinculados con un escribano.'}
          </p>
        )}
        {query.data && query.data.items.length > 0 && (
          <ul className="divide-y divide-line">
            {query.data.items.map((item) => (
              <li
                key={`${item.nombre_origen}-${item.escribano?.id ?? ''}`}
                className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-5 py-4 sm:px-6"
              >
                <div className="min-w-0">
                  <p className="font-semibold text-ink">{item.nombre_origen}</p>
                  <p className="text-sm text-ink-muted tabular-nums">
                    {anios(item)} · {formatMoney(item.total_aportes)} ·{' '}
                    {formatPuntos(item.total_puntos)} puntos
                  </p>
                  {item.escribano && (
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-sm">
                      <StatusIndicator
                        tone="warning"
                        label={item.estado === 'HEREDADA' ? 'Heredado' : 'Sugerido'}
                      />
                      <Link to={`/padron/escribanos/${item.escribano.id}`}>
                        {item.escribano.apellido_nombre} · Mat. {item.escribano.matricula_numero}
                      </Link>
                    </p>
                  )}
                </div>
                {puedeVincular && (
                  <Button
                    variant={aRevisar ? 'secondary' : 'ghost'}
                    icon={Link2}
                    onClick={() => {
                      setAbierto(item)
                    }}
                  >
                    {aRevisar ? 'Revisar' : 'Vincular'}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      {query.data && query.data.total > 0 && (
        <Pagination page={page} pageSize={PAGE_SIZE} total={query.data.total} onPage={setPage} />
      )}
      <VincularDialog
        item={abierto}
        onClose={() => {
          setAbierto(null)
        }}
      />
    </Panel>
  )
}

function CalculoPanel() {
  const { can } = useSession()
  const query = useQuery({ queryKey: ['previsional', 'calculo'], queryFn: fetchEstadoCalculo })
  const habilitado = query.data?.habilitado ?? false
  const [anio, setAnio] = useState('')
  return (
    <Panel
      title="Calcular puntos de un ejercicio"
      description="Acreditación de los puntos de un ejercicio cerrado a partir de los aportes ingresados."
    >
      <div className="space-y-4 px-5 py-5 sm:px-6">
        {query.data && !habilitado && (
          <Alert tone="warning" title="No disponible todavía">
            {query.data.motivo}
          </Alert>
        )}
        <div className="flex flex-wrap items-end gap-3">
          <Field
            label="Ejercicio (año de cierre)"
            inputMode="numeric"
            className="w-48 [&_input]:tabular-nums"
            disabled={!habilitado}
            value={anio}
            onChange={(e) => {
              setAnio(e.target.value.replace(/\D/g, '').slice(0, 4))
            }}
          />
          <Button icon={Calculator} disabled={!habilitado || !can('puntos:manage')}>
            Calcular puntos
          </Button>
        </div>
      </div>
    </Panel>
  )
}

/** Personal de la Caja: vínculo de la planilla histórica con el padrón y estado del cálculo. */
export function PuntosPage() {
  return (
    <>
      <PageHeader
        title="Aportes y puntos (Ley 7231)"
        description="Puntos por afiliado según la planilla histórica de la Caja. El informe de cada escribano está en su ficha del padrón."
      />
      <div className="mb-6">
        <Link
          to="/reportes/PUNTOS_EJERCICIOS"
          className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold"
        >
          <TableProperties aria-hidden="true" className="size-4" strokeWidth={2.25} />
          Resumen por ejercicio (total de aportes, afiliados, aporte medio y puntos)
        </Link>
      </div>
      <div className="space-y-6">
        <SinVincularPanel />
        <CalculoPanel />
      </div>
    </>
  )
}
