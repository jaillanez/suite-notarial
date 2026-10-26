import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CircleDashed, PenLine } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Pagination } from '../../components/ui/Pagination'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { formatMoney } from '../../lib/decimal'
import { useSession } from '../auth/session'
import { ConfirmacionHumana } from '../ia/componentes'
import {
  fetchCorrida,
  fetchObservaciones,
  firmarConformidad,
  type Area,
  type CorridaDetalle,
  type CuadraturaEntidad,
  type Entidad,
  type Severidad,
} from './api'
import { Cuadra } from './CorridasPage'
import {
  AREA,
  ENTIDAD,
  ESTADO,
  ESTADO_BOLETA_HISTORICA,
  MODO,
  ROL_DEL_AREA,
  TABLA_HOMOLOGACION,
  huellaCorta,
} from './labels'

const PAGE_SIZE = 25

function Ok({ ok }: { ok: boolean | undefined }) {
  if (ok === undefined) return <span className="text-ink-subtle">—</span>
  return ok ? (
    <StatusIndicator tone="success" label="Cuadra" />
  ) : (
    <StatusIndicator tone="danger" label="No cuadra" />
  )
}

function fallas(e: CuadraturaEntidad): string[] {
  const motivos: string[] = []
  if (e.control_filas !== e.leidas)
    motivos.push(
      `${ENTIDAD[e.entidad]}: el sistema anterior declara ${String(e.control_filas)} filas y el lote trae ${String(e.leidas)}`,
    )
  if (e.leidas !== e.cargadas + e.rechazadas)
    motivos.push(`${ENTIDAD[e.entidad]}: hay filas leídas que no se cargaron ni se rechazaron`)
  if (e.cuadra_importe === false) {
    if (e.filas_importe_ilegible)
      motivos.push(
        `${ENTIDAD[e.entidad]}: ${String(e.filas_importe_ilegible)} ${e.filas_importe_ilegible === 1 ? 'importe ilegible' : 'importes ilegibles'} (no se redondean)`,
      )
    else if (e.control_importe_error)
      motivos.push(`${ENTIDAD[e.entidad]}: ${e.control_importe_error}`)
    else
      motivos.push(
        `${ENTIDAD[e.entidad]}: el importe declarado (${formatMoney(e.control_importe ?? null)}) no coincide con lo leído (${formatMoney(e.importe_leido ?? null)})`,
      )
  }
  return motivos
}

function Veredicto({ c }: { c: CorridaDetalle }) {
  if (c.estado === 'FALLIDA')
    return (
      <Alert tone="danger" title="La corrida falló y no cargó nada">
        <p className="[overflow-wrap:anywhere]">{c.error}</p>
      </Alert>
    )
  if (!c.informe) return <Alert tone="info">La corrida todavía está en curso.</Alert>
  if (c.informe.cuadra)
    return (
      <Alert tone="success" title="Cuadra al centavo">
        Lo que declara el sistema anterior coincide con lo leído; lo leído es lo cargado más lo
        rechazado (cada rechazo tiene su observación) y el saldo de cada registro es el mismo en
        origen y destino.
      </Alert>
    )
  const motivos = c.informe.entidades.flatMap(fallas)
  if (c.informe.saldos.diferencias.length)
    motivos.push(
      `${String(c.informe.saldos.diferencias.length)} registros con saldo distinto entre origen y destino`,
    )
  return (
    <Alert tone="danger" title="No cuadra">
      <ul className="list-disc space-y-1 pl-5">
        {motivos.map((m) => (
          <li key={m}>{m}</li>
        ))}
      </ul>
    </Alert>
  )
}

function Num({ children }: { children: number | string }) {
  return <td className="px-3 py-3 text-right whitespace-nowrap tabular-nums">{children}</td>
}

function Cuadratura({ c }: { c: CorridaDetalle }) {
  const entidades = c.informe?.entidades ?? []
  const conImporte = entidades.filter((e) => e.importe_leido !== undefined)
  return (
    <Panel
      title="Cuadratura"
      description="Control: lo que declara el sistema anterior. Rechazadas: filas con observación bloqueante, que no se cargan."
    >
      <table className="hidden w-full text-sm sm:table">
        <thead className="bg-surface-sunken text-xs font-semibold text-ink-muted">
          <tr>
            <th scope="col" className="px-6 py-2.5 text-left">
              Filas
            </th>
            <th scope="col" className="px-3 py-2.5 text-right">
              Control
            </th>
            <th scope="col" className="px-3 py-2.5 text-right">
              Leídas
            </th>
            <th scope="col" className="px-3 py-2.5 text-right">
              Cargadas
            </th>
            <th scope="col" className="px-3 py-2.5 text-right">
              Rechazadas
            </th>
            <th scope="col" className="px-6 py-2.5 text-right">
              <span className="sr-only">Resultado</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {entidades.map((e) => (
            <tr key={e.entidad} className={e.cuadra_filas ? '' : 'bg-danger-50'}>
              <th scope="row" className="px-6 py-3 text-left font-semibold text-ink">
                {ENTIDAD[e.entidad]}
              </th>
              <Num>{e.control_filas}</Num>
              <Num>{e.leidas}</Num>
              <Num>{e.cargadas}</Num>
              <Num>{e.rechazadas}</Num>
              <td className="px-6 py-3 text-right">
                <Ok ok={e.cuadra_filas} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {conImporte.length > 0 && (
        <table className="hidden w-full border-t border-line text-sm sm:table">
          <thead className="bg-surface-sunken text-xs font-semibold text-ink-muted">
            <tr>
              <th scope="col" className="px-6 py-2.5 text-left">
                Importes
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                Control
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                Leído
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                Cargado
              </th>
              <th scope="col" className="px-3 py-2.5 text-right">
                Rechazado
              </th>
              <th scope="col" className="px-6 py-2.5 text-right">
                <span className="sr-only">Resultado</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {conImporte.map((e) => (
              <tr key={e.entidad} className={e.cuadra_importe ? '' : 'bg-danger-50'}>
                <th scope="row" className="px-6 py-3 text-left font-semibold text-ink">
                  {ENTIDAD[e.entidad]}
                  {Boolean(e.filas_importe_ilegible) && (
                    <span className="block text-xs font-normal text-danger-700">
                      {e.filas_importe_ilegible} ilegible{e.filas_importe_ilegible === 1 ? '' : 's'}
                    </span>
                  )}
                </th>
                <Num>{formatMoney(e.control_importe ?? null)}</Num>
                <Num>{formatMoney(e.importe_leido ?? null)}</Num>
                <Num>{formatMoney(e.importe_cargado ?? null)}</Num>
                <Num>{formatMoney(e.importe_rechazado ?? null)}</Num>
                <td className="px-6 py-3 text-right">
                  <Ok ok={e.cuadra_importe} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {/* Celular: una tarjeta por entidad, sin scroll horizontal. */}
      <ul className="divide-y divide-line sm:hidden">
        {entidades.map((e) => (
          <li key={e.entidad} className="px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <span className="font-semibold text-ink">{ENTIDAD[e.entidad]}</span>
              <Ok ok={e.cuadra_filas && e.cuadra_importe !== false} />
            </div>
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm tabular-nums">
              <dt className="text-ink-muted">Control</dt>
              <dd className="text-right">{e.control_filas}</dd>
              <dt className="text-ink-muted">Leídas</dt>
              <dd className="text-right">{e.leidas}</dd>
              <dt className="text-ink-muted">Cargadas</dt>
              <dd className="text-right">{e.cargadas}</dd>
              <dt className="text-ink-muted">Rechazadas</dt>
              <dd className="text-right">{e.rechazadas}</dd>
              {e.importe_leido !== undefined && (
                <>
                  <dt className="text-ink-muted">Importe control</dt>
                  <dd className="text-right">{formatMoney(e.control_importe ?? null)}</dd>
                  <dt className="text-ink-muted">Importe cargado</dt>
                  <dd className="text-right">{formatMoney(e.importe_cargado ?? null)}</dd>
                </>
              )}
            </dl>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

function Saldos({ c }: { c: CorridaDetalle }) {
  const s = c.informe?.saldos
  if (!s) return null
  return (
    <Panel
      title="Saldos por registro"
      description="Boletas no anuladas menos pagos, registro por registro."
    >
      <dl className="divide-y divide-line">
        {[
          ['Registros con boletas', String(s.registros)],
          ['Saldo de lo cargado, según el sistema anterior', formatMoney(s.deuda_total_origen)],
          ['Saldo de lo cargado, según la Suite', formatMoney(s.deuda_total_destino)],
        ].map(([etiqueta, valor]) => (
          <div key={etiqueta} className="flex flex-wrap justify-between gap-x-4 px-5 py-3 sm:px-6">
            <dt className="text-sm font-medium text-ink-muted">{etiqueta}</dt>
            <dd className="text-ink tabular-nums">{valor}</dd>
          </div>
        ))}
        {c.informe?.boletas_por_estado.map((b) => (
          <div key={b.estado} className="flex flex-wrap justify-between gap-x-4 px-5 py-3 sm:px-6">
            <dt className="text-sm font-medium text-ink-muted">
              Boletas {(ESTADO_BOLETA_HISTORICA[b.estado] ?? b.estado).toLowerCase()} ({b.filas})
            </dt>
            <dd className="text-ink tabular-nums">{formatMoney(b.importe)}</dd>
          </div>
        ))}
      </dl>
      {s.diferencias.length > 0 && (
        <div className="border-t border-line px-5 py-4 sm:px-6">
          <Alert tone="danger" title="Registros con saldo distinto">
            <ul className="space-y-1 tabular-nums">
              {s.diferencias.map((d) => (
                <li key={d.registro}>
                  Registro {d.registro}: origen {formatMoney(d.origen)}, Suite{' '}
                  {formatMoney(d.destino)}
                </li>
              ))}
            </ul>
          </Alert>
        </div>
      )}
    </Panel>
  )
}

function Observaciones({ c }: { c: CorridaDetalle }) {
  const [filtros, setFiltros] = useState({
    page: 1,
    severidad: '' as Severidad | '',
    entidad: '' as Entidad | '',
  })
  const query = useQuery({
    queryKey: ['migracion', 'observaciones', c.id, filtros],
    queryFn: () => fetchObservaciones(c.id, { ...filtros, pageSize: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const porCodigo = Object.entries(c.informe?.observaciones_por_codigo ?? {})
  return (
    <Panel
      title="Observaciones"
      description={
        c.informe
          ? `${String(c.informe.bloqueantes)} bloqueantes (la fila no se carga) · ${String(c.informe.advertencias)} advertencias (se carga y queda para revisar)`
          : undefined
      }
    >
      {porCodigo.length > 0 && (
        <ul
          className="flex flex-wrap gap-2 border-b border-line px-5 py-4 sm:px-6"
          aria-label="Observaciones por código"
        >
          {porCodigo.map(([codigo, cantidad]) => (
            <li
              key={codigo}
              className="rounded-full bg-surface-sunken px-3 py-1 text-xs font-semibold text-ink-muted tabular-nums"
            >
              {codigo} · {cantidad}
            </li>
          ))}
        </ul>
      )}
      <div className="grid gap-4 border-b border-line px-5 py-4 sm:grid-cols-2 sm:px-6">
        <Select
          label="Severidad"
          value={filtros.severidad}
          onChange={(e) => {
            setFiltros((f) => ({ ...f, severidad: e.target.value as Severidad | '', page: 1 }))
          }}
          options={[
            { value: '', label: 'Todas' },
            { value: 'BLOQUEANTE', label: 'Bloqueantes' },
            { value: 'ADVERTENCIA', label: 'Advertencias' },
          ]}
        />
        <Select
          label="Archivo"
          value={filtros.entidad}
          onChange={(e) => {
            setFiltros((f) => ({ ...f, entidad: e.target.value as Entidad | '', page: 1 }))
          }}
          options={[
            { value: '', label: 'Todos' },
            ...(Object.keys(ENTIDAD) as Entidad[]).map((e) => ({ value: e, label: ENTIDAD[e] })),
          ]}
        />
      </div>
      {query.isError && (
        <div className="px-5 py-4 sm:px-6">
          <Alert tone="danger">{toProblem(query.error).detail}</Alert>
        </div>
      )}
      <ul className="divide-y divide-line" aria-busy={query.isFetching}>
        {query.data?.items.length === 0 && (
          <li className="px-5 py-8 text-center text-ink-muted sm:px-6">
            {filtros.severidad || filtros.entidad
              ? 'Ninguna observación coincide con los filtros.'
              : 'Sin observaciones: todas las filas se pudieron cargar.'}
          </li>
        )}
        {query.data?.items.map((o, i) => (
          <li
            key={`${o.entidad}-${String(o.fila)}-${o.codigo}-${String(i)}`}
            className="flex gap-4 px-5 py-3 sm:px-6"
          >
            <span className="mt-0.5 shrink-0">
              <StatusIndicator
                tone={o.severidad === 'BLOQUEANTE' ? 'danger' : 'warning'}
                label={o.severidad === 'BLOQUEANTE' ? 'Bloqueante' : 'Advertencia'}
              />
            </span>
            <span className="min-w-0 text-sm">
              <span className="block text-ink">{o.mensaje}</span>
              <span className="block text-ink-muted tabular-nums [overflow-wrap:anywhere]">
                {ENTIDAD[o.entidad]}
                {o.fila > 0 && ` · línea ${String(o.fila)}`}
                {o.codigo_legado && ` · código ${o.codigo_legado}`} · {o.codigo}
              </span>
            </span>
          </li>
        ))}
      </ul>
      <Pagination
        page={filtros.page}
        pageSize={PAGE_SIZE}
        total={query.data?.total ?? 0}
        onPage={(page) => {
          setFiltros((f) => ({ ...f, page }))
        }}
      />
    </Panel>
  )
}

function Conformidad({ c }: { c: CorridaDetalle }) {
  const { user, can } = useSession()
  const queryClient = useQueryClient()
  const firmadas = new Map(c.conformidades.map((x) => [x.area, x]))
  const misAreas = (['TESORERIA', 'CAJA'] as Area[]).filter(
    (a) => user?.roles.includes(ROL_DEL_AREA[a]) && !firmadas.has(a),
  )
  const yaFirme = c.conformidades.some((x) => x.firmante === user?.full_name)
  const [area, setArea] = useState<Area | ''>(misAreas[0] ?? '')
  const [observaciones, setObservaciones] = useState('')
  const [revisado, setRevisado] = useState(false)
  const firmar = useMutation({
    mutationFn: () =>
      firmarConformidad(c.id, {
        area: area as Area,
        observaciones: observaciones.trim() || null,
      }),
    onSuccess: async (detalle) => {
      queryClient.setQueryData(['migracion', 'corrida', c.id], detalle)
      await queryClient.invalidateQueries({ queryKey: ['migracion', 'corridas'] })
    },
  })
  if (c.modo !== 'SIMULACRO') return null
  const puedeFirmar =
    can('migracion:conformar') &&
    c.estado === 'SIMULADA' &&
    c.cuadra === true &&
    misAreas.length > 0 &&
    !yaFirme

  return (
    <Panel
      title="Conformidad de Tesorería y Caja"
      description="La carga definitiva exige la conformidad de ambas áreas sobre un simulacro del mismo lote que haya cuadrado. Firman personas distintas."
    >
      <dl className="divide-y divide-line">
        {(['TESORERIA', 'CAJA'] as Area[]).map((a) => {
          const firma = firmadas.get(a)
          return (
            <div
              key={a}
              className="flex flex-wrap items-start justify-between gap-3 px-5 py-4 sm:px-6"
            >
              <dt className="font-semibold text-ink">{AREA[a]}</dt>
              <dd className="text-right text-sm">
                {firma ? (
                  <>
                    <StatusIndicator tone="success" label={`Firmó ${firma.firmante}`} />
                    <span className="mt-1 block text-ink-muted tabular-nums">
                      {formatLocalDateTime(new Date(firma.firmada_en))}
                    </span>
                    {firma.observaciones && (
                      <span className="mt-1 block max-w-[48ch] text-ink">
                        {firma.observaciones}
                      </span>
                    )}
                  </>
                ) : (
                  <StatusIndicator tone="unknown" label="Pendiente" />
                )}
              </dd>
            </div>
          )
        })}
      </dl>
      {puedeFirmar && (
        <div className="space-y-4 border-t border-line px-5 py-5 sm:px-6">
          {misAreas.length > 1 && (
            <Select
              label="Firmo por"
              value={area}
              onChange={(e) => {
                setArea(e.target.value as Area)
              }}
              options={misAreas.map((a) => ({ value: a, label: AREA[a] }))}
            />
          )}
          <TextArea
            label="Observaciones (opcional)"
            rows={2}
            value={observaciones}
            onChange={(e) => {
              setObservaciones(e.target.value)
            }}
          />
          <ConfirmacionHumana checked={revisado} onChange={setRevisado}>
            Revisé la cuadratura y las observaciones de este simulacro y doy conformidad por{' '}
            {area ? AREA[area] : 'mi área'}.
          </ConfirmacionHumana>
          {firmar.isError && <Alert tone="danger">{toProblem(firmar.error).detail}</Alert>}
          <div className="flex justify-end">
            <Button
              variant="primary"
              icon={PenLine}
              busy={firmar.isPending}
              busyLabel="Firmando…"
              disabled={!revisado || !area}
              onClick={() => {
                firmar.mutate()
              }}
            >
              Firmar conformidad{area ? ` de ${AREA[area]}` : ''}
            </Button>
          </div>
        </div>
      )}
      {!puedeFirmar && c.estado === 'SIMULADA' && c.cuadra === false && (
        <p className="border-t border-line px-5 py-4 text-sm text-ink-muted sm:px-6">
          Este simulacro no cuadró: no se le puede dar conformidad.
        </p>
      )}
    </Panel>
  )
}

function Homologacion({ c }: { c: CorridaDetalle }) {
  const tablas = Object.entries(c.homologacion_tablas)
  return (
    <Panel
      title="Tabla de homologación"
      description={`Cómo se tradujeron los códigos del sistema anterior (${c.homologacion}, huella ${huellaCorta(c.huella_homologacion)}). La conformidad cubre este lote y esta tabla.`}
    >
      <div className="divide-y divide-line">
        {tablas.map(([tabla, valores]) => (
          <details key={tabla} className="group px-5 py-3 sm:px-6">
            <summary className="flex min-h-11 cursor-pointer items-center justify-between gap-3 font-medium text-ink">
              {TABLA_HOMOLOGACION[tabla] ?? tabla}
              <span className="text-sm font-normal text-ink-muted tabular-nums">
                {Object.keys(valores).length} códigos
              </span>
            </summary>
            <dl className="mt-2 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
              {Object.entries(valores).map(([origen, destino]) => (
                <div key={origen} className="contents">
                  <dt className="font-mono text-ink-muted [overflow-wrap:anywhere]">{origen}</dt>
                  <dd className="text-ink">{destino}</dd>
                </div>
              ))}
            </dl>
          </details>
        ))}
      </div>
    </Panel>
  )
}

function Definitiva({ c }: { c: CorridaDetalle }) {
  if (c.modo === 'DEFINITIVA') return null
  const pendiente = c.pendiente_para_definitiva
  return (
    <Panel title="Carga definitiva de este lote">
      <div className="px-5 py-4 sm:px-6">
        {pendiente.length === 0 ? (
          <Alert tone="success" title="Habilitada">
            Se ejecuta por consola con el mismo lote (misma huella) y la homologación aprobada, con
            respaldo previo: ver el manual de corte.
          </Alert>
        ) : (
          <ul className="space-y-2 text-sm text-ink">
            {pendiente.map((m) => (
              <li key={m} className="flex gap-2">
                <CircleDashed
                  aria-hidden="true"
                  className="mt-0.5 size-4 shrink-0 text-ink-subtle"
                  strokeWidth={2.25}
                />
                <span>{m}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  )
}

export function CorridaPage() {
  const { id = '' } = useParams()
  const corrida = useQuery({
    queryKey: ['migracion', 'corrida', id],
    queryFn: () => fetchCorrida(id),
  })
  const c = corrida.data

  return (
    <>
      <Link
        to="/migracion"
        className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-medium"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Migración
      </Link>
      {corrida.isPending && (
        <div aria-busy="true" className="h-64 animate-pulse rounded-panel bg-brand-50" />
      )}
      {corrida.isError && <Alert tone="danger">{toProblem(corrida.error).detail}</Alert>}
      {c && (
        <>
          <PageHeader
            title={`${MODO[c.modo]} del ${formatLocalDateTime(new Date(c.created_at))}`}
            description={`Ejecutó ${c.operador}${c.duracion_ms !== null ? ` · ${(c.duracion_ms / 1000).toFixed(1).replace('.', ',')} s` : ''}`}
          />
          <div className="-mt-4 mb-6 flex flex-wrap gap-2">
            <Cuadra corrida={c} />
            <StatusIndicator tone={ESTADO[c.estado].tone} label={ESTADO[c.estado].label} />
          </div>
          <div className="space-y-6">
            <Veredicto c={c} />
            {c.homologacion_ejemplo && (
              <Alert tone="warning" title="Homologación de ejemplo">
                Los códigos del sistema anterior se tradujeron con la tabla de ejemplo. Sirve para
                ensayar; la carga definitiva exige la tabla aprobada por la Caja.
              </Alert>
            )}
            {c.informe && <Cuadratura c={c} />}
            <Saldos c={c} />
            <Observaciones c={c} />
            <Homologacion c={c} />
            <Conformidad c={c} />
            <Definitiva c={c} />
            <p className="text-xs text-ink-muted [overflow-wrap:anywhere]">
              Lote <span className="font-mono">{huellaCorta(c.huella_lote)}</span> · homologación{' '}
              {c.homologacion}
              {c.informe &&
                ` · codificación ${Object.entries(c.informe.codificaciones)
                  .map(([archivo, cod]) => `${archivo} ${cod}`)
                  .join(', ')}`}
            </p>
          </div>
        </>
      )}
    </>
  )
}
