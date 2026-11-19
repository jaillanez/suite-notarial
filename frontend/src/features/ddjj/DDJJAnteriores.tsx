import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { StatusIndicator, type Tone } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Field } from '../../components/ui/Field'
import { Pagination } from '../../components/ui/Pagination'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { formatMoney } from '../../lib/decimal'
import { formatDate } from '../padron/labels'
import { fetchAnterior, fetchAnteriores, type BoletaAnterior, type DDJJAnterior } from './api'
import { formatPeriodo } from './labels'

const PAGE_SIZE = 20

/** Importe de la API («1234.50») en centavos, sin pasar por punto flotante. */
function centavos(importe: string): bigint {
  const [entero = '0', decimales = ''] = importe.split('.')
  return BigInt(entero) * 100n + BigInt((decimales + '00').slice(0, 2))
}

/** Cómo quedó el pago de la DDJJ: lo dicen las boletas del sistema anterior y sus pagos. */
function estadoPago(d: DDJJAnterior): { tone: Tone; label: string } {
  const boletas = centavos(d.total_boletas)
  const pagado = centavos(d.total_pagado)
  if (boletas === 0n) return { tone: 'unknown', label: 'Sin boleta' }
  if (pagado >= boletas) return { tone: 'success', label: 'Pagada' }
  if (pagado > 0n) return { tone: 'warning', label: 'Pago parcial' }
  return { tone: 'danger', label: 'Impaga' }
}

const ESTADO_BOLETA: Record<BoletaAnterior['estado'], { tone: Tone; label: string }> = {
  PAGADA: { tone: 'success', label: 'Pagada' },
  IMPAGA: { tone: 'danger', label: 'Impaga' },
  ANULADA: { tone: 'unknown', label: 'Anulada' },
}

const PROTOCOLO_CORTO: Record<string, string> = { GENERAL: 'Gral.', AUXILIAR: 'Aux.' }

/** DDJJ del sistema anterior en «Declaraciones juradas»: el histórico migrado, de solo lectura,
 * con el mismo alcance que las de la Suite. */
export function AnterioresPanel() {
  const [filtros, setFiltros] = useState({ page: 1, registro: '', periodo: '' })
  const query = useQuery({
    queryKey: ['ddjj', 'anteriores', filtros],
    queryFn: () => fetchAnteriores({ ...filtros, pageSize: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const filas = query.data?.items ?? []
  const total = query.data?.total ?? 0
  if (query.isSuccess && total === 0 && !filtros.registro && !filtros.periodo) return null

  return (
    <Panel
      className="mt-6"
      title="Del sistema anterior"
      description="Las declaraciones juradas que se presentaron en el sistema anterior, con sus actos y boletas. Son de solo lectura."
    >
      <div className="grid gap-4 border-b border-line px-5 py-4 sm:grid-cols-[12rem_12rem] sm:px-6">
        <Field
          label="N° de registro"
          inputMode="numeric"
          autoComplete="off"
          value={filtros.registro}
          onChange={(e) => {
            const registro = e.target.value.replace(/\D/g, '')
            setFiltros((f) => ({ ...f, registro, page: 1 }))
          }}
        />
        <Field
          label="Período"
          type="month"
          value={filtros.periodo}
          onChange={(e) => {
            setFiltros((f) => ({ ...f, periodo: e.target.value, page: 1 }))
          }}
        />
      </div>
      {query.isError && (
        <div className="px-5 py-4 sm:px-6">
          <Alert tone="danger">{toProblem(query.error).detail}</Alert>
        </div>
      )}
      <ul className="divide-y divide-line" aria-busy={query.isFetching}>
        {query.isPending &&
          Array.from({ length: 4 }, (_, i) => (
            <li key={i} className="px-5 py-4 sm:px-6">
              <span className="block h-10 w-full animate-pulse rounded-control bg-brand-50" />
            </li>
          ))}
        {query.isSuccess && filas.length === 0 && (
          <li className="px-5 py-10 text-center text-ink-muted sm:px-6">
            Ninguna declaración del sistema anterior coincide con los filtros.
          </li>
        )}
        {filas.map((d) => {
          const estado = estadoPago(d)
          return (
            <li key={`${d.registro_id}-${d.periodo}`}>
              <Link
                to={`/ddjj/anterior/${d.registro_id}/${d.periodo}`}
                className="group flex items-center gap-4 px-5 py-4 text-ink no-underline hover:bg-brand-50 sm:px-6"
              >
                <span className="w-24 shrink-0 text-xl font-semibold text-brand-900 tabular-nums">
                  {formatPeriodo(d.periodo)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-brand-800 group-hover:underline">
                    Registro N° {d.numero_registro}
                  </span>
                  <span className="block text-sm text-ink-muted tabular-nums">
                    {d.cantidad_actos} {d.cantidad_actos === 1 ? 'acto' : 'actos'} · Aportes{' '}
                    {formatMoney(d.total_aportes)}
                    {centavos(d.total_boletas) > 0n &&
                      ` · Boletas ${formatMoney(d.total_boletas)} · Pagado ${formatMoney(d.total_pagado)}`}
                  </span>
                </span>
                <StatusIndicator tone={estado.tone} label={estado.label} />
                <ChevronRight
                  aria-hidden="true"
                  className="hidden size-5 shrink-0 text-ink-subtle group-hover:text-brand-800 sm:block"
                />
              </Link>
            </li>
          )
        })}
      </ul>
      <Pagination
        page={filtros.page}
        pageSize={PAGE_SIZE}
        total={total}
        onPage={(page) => {
          setFiltros((f) => ({ ...f, page }))
        }}
      />
    </Panel>
  )
}

/** Una DDJJ del sistema anterior: sus actos y sus boletas con los pagos, de solo lectura. */
export function DDJJAnteriorPage() {
  const { registroId = '', periodo = '' } = useParams()
  const query = useQuery({
    queryKey: ['ddjj', 'anterior', registroId, periodo],
    queryFn: () => fetchAnterior(registroId, periodo),
  })

  return (
    <>
      <Link
        to="/ddjj"
        className="mb-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-brand-800 no-underline hover:underline"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Declaraciones juradas
      </Link>
      {query.isError && <Alert tone="danger">{toProblem(query.error).detail}</Alert>}
      {query.isPending && (
        <div className="grid gap-3" aria-busy="true">
          {Array.from({ length: 4 }, (_, i) => (
            <span key={i} className="block h-12 animate-pulse rounded-control bg-brand-50" />
          ))}
        </div>
      )}
      {query.data && (
        <>
          <PageHeader
            title={`DDJJ ${formatPeriodo(query.data.resumen.periodo)}`}
            description={`Registro N° ${String(query.data.resumen.numero_registro)} · Presentada en el sistema anterior. Es de solo lectura.`}
          />
          <Panel
            title="Actos declarados"
            description={`${String(query.data.actos.length)} ${query.data.actos.length === 1 ? 'acto' : 'actos'} · Aportes ${formatMoney(query.data.resumen.total_aportes)}`}
          >
            {query.data.actos.length === 0 ? (
              <p className="px-5 py-8 text-center text-ink-muted sm:px-6">
                La declaración no tuvo actos.
              </p>
            ) : (
              <ul className="divide-y divide-line">
                {query.data.actos.map((a) => (
                  <li
                    key={a.id}
                    className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-5 py-3 sm:flex-nowrap sm:px-6"
                  >
                    <span className="w-28 shrink-0 font-semibold text-ink tabular-nums">
                      {a.tipo_protocolo ? `${PROTOCOLO_CORTO[a.tipo_protocolo] ?? ''} ` : ''}N°{' '}
                      {a.numero_escritura}
                      {a.folio !== null && (
                        <span className="block text-sm font-normal text-ink-muted">
                          Folio {a.folio}
                        </span>
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-ink">
                        {a.naturaleza}
                        {a.exento && ' · Exento'}
                      </span>
                      <span className="block text-sm text-ink-muted tabular-nums">
                        {[a.fecha_acto && formatDate(a.fecha_acto), a.escribano]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                    </span>
                    <span className="text-right tabular-nums sm:w-40">
                      {a.base_imponible !== null && (
                        <span className="block text-sm text-ink-muted">
                          Base {formatMoney(a.base_imponible)}
                        </span>
                      )}
                      <span className="block font-semibold text-ink">{formatMoney(a.aporte)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          <Panel className="mt-6" title="Boletas">
            {query.data.boletas.length === 0 ? (
              <p className="px-5 py-8 text-center text-ink-muted sm:px-6">
                El sistema anterior no registra boletas de este mes.
              </p>
            ) : (
              <ul className="divide-y divide-line">
                {query.data.boletas.map((b) => {
                  const estado = ESTADO_BOLETA[b.estado]
                  return (
                    <li
                      key={b.id}
                      className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-4 sm:px-6"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block font-semibold text-ink">
                          Boleta {b.numero ?? 'sin número'}
                        </span>
                        <span className="block text-sm text-ink-muted tabular-nums">
                          Emitida {formatDate(b.fecha_emision)} · Vence{' '}
                          {formatDate(b.fecha_vencimiento)}
                          {b.fecha_pago && ` · Pagada el ${formatDate(b.fecha_pago)}`}
                        </span>
                      </span>
                      <span className="text-right tabular-nums">
                        <span className="block font-semibold text-ink">
                          {formatMoney(b.importe)}
                        </span>
                        {centavos(b.pagado) > 0n && (
                          <span className="block text-sm text-ink-muted">
                            Pagado {formatMoney(b.pagado)}
                          </span>
                        )}
                      </span>
                      <StatusIndicator tone={estado.tone} label={estado.label} />
                    </li>
                  )
                })}
              </ul>
            )}
          </Panel>
        </>
      )}
    </>
  )
}
