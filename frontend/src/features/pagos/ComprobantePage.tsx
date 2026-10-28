import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CircleCheck, CircleX, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { Panel } from '../../components/ui/Panel'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { formatMoney, normalizeDecimalInput } from '../../lib/decimal'
import { formatPeriodo, registroLabel } from '../ddjj/labels'
import { formatDate, todayIso } from '../padron/labels'
import {
  aprobarComprobante,
  fetchArchivo,
  fetchComprobante,
  rechazarComprobante,
  type Comprobante,
} from './api'
import { ESTADO_COMPROBANTE, ESTADO_PAGO_MP, MOTIVOS_FRECUENTES, formatTamano } from './labels'

function Par({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 px-5 py-3 sm:px-6">
      <dt className="shrink-0 text-sm font-medium text-ink-muted">{label}</dt>
      <dd className="min-w-0 text-right break-words text-ink tabular-nums">{children}</dd>
    </div>
  )
}

/** Visor del archivo: lo trae como Blob (con la sesión) y lo muestra sin salir de la página. */
function Visor({ comprobante }: { comprobante: Comprobante }) {
  const query = useQuery({
    queryKey: ['pagos', 'archivo', comprobante.id],
    queryFn: () => fetchArchivo(comprobante.id),
    staleTime: Infinity,
    retry: false,
  })
  // Una URL local por archivo; se libera al cambiar de comprobante o salir de la página.
  const url = useMemo(() => (query.data ? URL.createObjectURL(query.data) : null), [query.data])
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url)
    },
    [url],
  )
  const esPdf = comprobante.mime_type === 'application/pdf'

  return (
    <Panel
      title="Comprobante"
      description={`${comprobante.nombre_original ?? ''} · ${formatTamano(comprobante.tamano_bytes ?? 0)}`}
      actions={
        url ? (
          <a
            href={url}
            target="_blank"
            rel="noopener"
            className="inline-flex min-h-11 items-center text-sm font-medium"
          >
            Abrir en otra pestaña
          </a>
        ) : undefined
      }
    >
      <div className="bg-surface-sunken">
        {query.isPending && (
          <div aria-busy="true" className="h-[32rem] animate-pulse bg-brand-50" />
        )}
        {query.isError && (
          <div className="p-5 sm:p-6">
            <Alert tone="danger" title="No se puede mostrar el archivo">
              {toProblem(query.error).detail}
            </Alert>
          </div>
        )}
        {url && esPdf && (
          <iframe
            src={url}
            title={`Comprobante ${comprobante.nombre_original ?? ''}`}
            className="block h-[32rem] w-full lg:h-[44rem]"
          />
        )}
        {url && !esPdf && (
          <img
            src={url}
            alt={`Comprobante ${comprobante.nombre_original ?? ''}`}
            className="mx-auto block max-h-[44rem] w-auto max-w-full object-contain"
          />
        )}
      </div>
    </Panel>
  )
}

/** Pago informado por Mercado Pago: no hay archivo, sino lo que la Suite consultó a su API. */
function PagoMercadoPagoPanel({ c }: { c: Comprobante }) {
  const mp = c.mercado_pago
  return (
    <Panel
      title="Pago con Mercado Pago"
      description="Datos consultados a Mercado Pago. Confirmá el pago contra la liquidación de Mercado Pago antes de aprobarlo."
    >
      {mp ? (
        <dl className="divide-y divide-line">
          <Par label="Estado en Mercado Pago">{ESTADO_PAGO_MP[mp.estado]}</Par>
          <Par label="N° de operación">{mp.mp_payment_id ?? '—'}</Par>
          <Par label="Medio de pago">{mp.medio_pago ?? '—'}</Par>
          <Par label="Aprobado">
            {mp.aprobado_en ? formatLocalDateTime(new Date(mp.aprobado_en)) : '—'}
          </Par>
          <Par label="Importe pagado">{formatMoney(mp.importe_pagado)}</Par>
          <Par label="Comisión de Mercado Pago (la absorbe la Caja)">
            {formatMoney(mp.comision)}
          </Par>
          <Par label="Neto a acreditar">{formatMoney(mp.importe_neto)}</Par>
        </dl>
      ) : (
        <div className="px-5 py-5 sm:px-6">
          <Alert tone="warning">No se encontró el registro del pago en Mercado Pago.</Alert>
        </div>
      )}
      {mp && (mp.estado === 'refunded' || mp.estado === 'charged_back') && (
        <div className="px-5 pb-5 sm:px-6">
          <Alert tone="danger" title="Mercado Pago revirtió este pago">
            El pago figura como {ESTADO_PAGO_MP[mp.estado].toLowerCase()}: no lo apruebes.
          </Alert>
        </div>
      )}
    </Panel>
  )
}

function Cotejo({ c }: { c: Comprobante }) {
  const coincide = c.diferencia === '0.00'
  return (
    <Panel title="Cotejo con la boleta">
      <dl className="divide-y divide-line">
        <Par label="Boleta">
          <Link to={`/ddjj/${c.boleta.ddjj_id}`}>N° {c.boleta.numero}</Link>
        </Par>
        <Par label="Registro">{registroLabel(c.boleta.registro)}</Par>
        <Par label="Período">{formatPeriodo(c.boleta.periodo)}</Par>
        <Par label="Pagar hasta">{formatDate(c.boleta.fecha_pago)}</Par>
        <Par label="Total de la boleta">
          <span className="font-semibold">{formatMoney(c.boleta.total_a_pagar)}</span>
        </Par>
        <Par label="Importe declarado">
          <span className="font-semibold">{formatMoney(c.importe_declarado)}</span>
        </Par>
        <div
          className={`flex items-center justify-between gap-4 px-5 py-3 sm:px-6 ${coincide ? 'bg-success-50 text-success-700' : 'bg-warning-50 text-warning-700'}`}
        >
          <dt className="flex items-center gap-2 text-sm font-semibold">
            {coincide ? (
              <CircleCheck aria-hidden="true" className="size-4" strokeWidth={2.25} />
            ) : (
              <TriangleAlert aria-hidden="true" className="size-4" strokeWidth={2.25} />
            )}
            {coincide ? 'Coincide con el total' : 'Diferencia'}
          </dt>
          <dd className="font-semibold tabular-nums">
            {coincide ? formatMoney('0.00') : formatMoney(c.diferencia)}
          </dd>
        </div>
        <Par label={c.origen === 'MERCADO_PAGO' ? 'Pago aprobado' : 'Transferencia'}>
          {formatDate(c.fecha_transferencia)}
        </Par>
        <Par label="N° de operación">{c.numero_operacion}</Par>
        <Par label="Banco de origen">{c.banco_origen ?? '—'}</Par>
        <Par label="Adjuntado por">{c.subido_por ?? '—'}</Par>
        <Par label="Recibido">{formatLocalDateTime(new Date(c.created_at))}</Par>
      </dl>
    </Panel>
  )
}

function Resolucion({ c }: { c: Comprobante }) {
  const conc = c.conciliacion
  if (!conc) return null
  const aprobado = conc.resultado === 'APROBADO'
  return (
    <Panel title={aprobado ? 'Pago confirmado' : 'Comprobante rechazado'}>
      <dl className="divide-y divide-line">
        {aprobado ? (
          <>
            <Par label="Importe acreditado">{formatMoney(conc.importe_confirmado)}</Par>
            <Par label="Acreditación">{formatDate(conc.fecha_acreditacion)}</Par>
            <Par label="Extracto">{conc.identificador_extracto ?? '—'}</Par>
          </>
        ) : (
          <div className="px-5 py-3 sm:px-6">
            <dt className="text-sm font-medium text-ink-muted">Motivo</dt>
            <dd className="mt-0.5 text-ink">{conc.observaciones}</dd>
          </div>
        )}
        {aprobado && conc.observaciones && (
          <div className="px-5 py-3 sm:px-6">
            <dt className="text-sm font-medium text-ink-muted">Observaciones</dt>
            <dd className="mt-0.5 text-ink">{conc.observaciones}</dd>
          </div>
        )}
        <Par label="Revisó">{conc.operador ?? '—'}</Par>
        <Par label="Fecha">{formatLocalDateTime(new Date(conc.created_at))}</Par>
      </dl>
    </Panel>
  )
}

function useInvalidate(id: string) {
  const queryClient = useQueryClient()
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['pagos', 'comprobante', id] })
    await queryClient.invalidateQueries({ queryKey: ['pagos', 'mesa'] })
  }
}

function AprobarPanel({ c }: { c: Comprobante }) {
  const invalidate = useInvalidate(c.id)
  const hoy = todayIso()
  const [form, setForm] = useState({
    importe: '',
    fecha: '',
    extracto: '',
    observaciones: '',
  })
  const [confirmando, setConfirmando] = useState(false)
  const importe = normalizeDecimalInput(form.importe)
  const fueraDePlazo = form.fecha !== '' && form.fecha > c.boleta.fecha_pago
  const save = useMutation({
    mutationFn: () =>
      aprobarComprobante(c.id, {
        importe_confirmado: importe,
        fecha_acreditacion: form.fecha,
        identificador_extracto: form.extracto.trim() || null,
        observaciones: form.observaciones.trim() || null,
      }),
    onSuccess: async () => {
      setConfirmando(false)
      await invalidate()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const completo =
    importe !== '' && form.fecha !== '' && (!fueraDePlazo || form.observaciones.trim().length >= 5)

  return (
    <Panel
      title="Confirmar el pago"
      description="Cargá lo que figura en el extracto bancario, no lo que declaró el escribano."
    >
      <div className="grid gap-4 px-5 py-4 sm:grid-cols-2 sm:px-6">
        <Field
          label="Importe acreditado ($)"
          inputMode="decimal"
          autoComplete="off"
          className="[&_input]:tabular-nums"
          value={form.importe}
          onChange={(e) => {
            setForm((f) => ({ ...f, importe: e.target.value }))
          }}
        />
        <Field
          label="Fecha de acreditación"
          type="date"
          className="[&_input]:tabular-nums"
          min={c.fecha_transferencia}
          max={hoy}
          value={form.fecha}
          onChange={(e) => {
            setForm((f) => ({ ...f, fecha: e.target.value }))
          }}
        />
        <Field
          className="sm:col-span-2"
          label="Identificador en el extracto (opcional)"
          maxLength={100}
          autoComplete="off"
          value={form.extracto}
          onChange={(e) => {
            setForm((f) => ({ ...f, extracto: e.target.value }))
          }}
        />
        {fueraDePlazo && (
          <div className="sm:col-span-2">
            <Alert tone="warning">
              Se acreditó después de la fecha de pago de la boleta (
              {formatDate(c.boleta.fecha_pago)}). Dejá constancia en observaciones.
            </Alert>
          </div>
        )}
        <TextArea
          className="sm:col-span-2"
          label={fueraDePlazo ? 'Observaciones' : 'Observaciones (opcional)'}
          hint={fueraDePlazo ? 'Obligatorias, al menos 5 caracteres.' : undefined}
          maxLength={1000}
          value={form.observaciones}
          onChange={(e) => {
            setForm((f) => ({ ...f, observaciones: e.target.value }))
          }}
        />
      </div>
      <div className="flex justify-end border-t border-line bg-surface-sunken px-5 py-4 sm:px-6">
        <Button
          variant="primary"
          icon={CircleCheck}
          disabled={!completo}
          onClick={() => {
            setConfirmando(true)
          }}
        >
          Confirmar pago
        </Button>
      </div>
      <Dialog
        open={confirmando}
        onClose={() => {
          save.reset()
          setConfirmando(false)
        }}
        title={`Confirmar el pago de la boleta N° ${String(c.boleta.numero)}`}
        description="La boleta pasa a pagada y el asiento de conciliación queda registrado. No se puede deshacer."
        footer={
          <>
            <Button
              onClick={() => {
                setConfirmando(false)
              }}
            >
              Revisar de nuevo
            </Button>
            <Button
              variant="primary"
              icon={CircleCheck}
              busy={save.isPending}
              busyLabel="Confirmando…"
              onClick={() => {
                save.mutate()
              }}
            >
              Confirmar pago
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          {problem && <Alert tone="danger">{problem.detail}</Alert>}
          <dl className="divide-y divide-line rounded-control border border-line">
            <Par label="Total de la boleta">{formatMoney(c.boleta.total_a_pagar)}</Par>
            <Par label="Importe acreditado">{formatMoney(importe || null)}</Par>
            <Par label="Acreditación">{formatDate(form.fecha || null)}</Par>
          </dl>
        </div>
      </Dialog>
    </Panel>
  )
}

function RechazarPanel({ c }: { c: Comprobante }) {
  const invalidate = useInvalidate(c.id)
  const [motivo, setMotivo] = useState('')
  const save = useMutation({
    mutationFn: () => rechazarComprobante(c.id, motivo.trim()),
    onSuccess: invalidate,
  })
  return (
    <Panel
      title="Rechazar el comprobante"
      description="La boleta sigue pendiente y el escribano recibe el motivo por correo."
    >
      <div className="grid gap-4 px-5 py-4 sm:px-6">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <div>
          <p className="text-sm font-medium text-ink">Motivos frecuentes</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {MOTIVOS_FRECUENTES.map((m) => (
              <Button
                key={m}
                variant="ghost"
                className="border-line! text-left font-medium aria-pressed:border-brand-700! aria-pressed:bg-brand-50"
                aria-pressed={motivo === m}
                onClick={() => {
                  setMotivo(m)
                }}
              >
                {m}
              </Button>
            ))}
          </div>
        </div>
        <TextArea
          label="Motivo"
          hint="Obligatorio. El escribano lo lee tal cual."
          maxLength={1000}
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
        />
      </div>
      <div className="flex justify-end border-t border-line bg-surface-sunken px-5 py-4 sm:px-6">
        <Button
          variant="danger"
          icon={CircleX}
          busy={save.isPending}
          busyLabel="Rechazando…"
          disabled={motivo.trim().length < 5}
          onClick={() => {
            save.mutate()
          }}
        >
          Rechazar comprobante
        </Button>
      </div>
    </Panel>
  )
}

export function ComprobantePage() {
  const { id = '' } = useParams()
  const query = useQuery({
    queryKey: ['pagos', 'comprobante', id],
    queryFn: () => fetchComprobante(id),
  })
  const c = query.data

  return (
    <>
      <Link
        to="/tesoreria/conciliacion"
        className="mb-6 inline-flex min-h-11 items-center gap-2 text-sm font-medium"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Conciliación de pagos
      </Link>
      {query.isError && <Alert tone="danger">{toProblem(query.error).detail}</Alert>}
      {query.isPending && (
        <div aria-busy="true" aria-live="polite" className="grid gap-4">
          <span className="block h-9 w-72 animate-pulse rounded-control bg-brand-50" />
          <span className="block h-96 animate-pulse rounded-panel bg-brand-50" />
        </div>
      )}
      {c && (
        <div className="grid gap-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-brand-900 tabular-nums sm:text-[1.75rem]">
              Comprobante de la boleta N° {c.boleta.numero}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <span className="text-ink-muted tabular-nums">
                {registroLabel(c.boleta.registro)} · {formatPeriodo(c.boleta.periodo)}
              </span>
              <StatusIndicator
                tone={ESTADO_COMPROBANTE[c.estado].tone}
                label={ESTADO_COMPROBANTE[c.estado].label}
              />
            </div>
          </div>
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            {c.origen === 'MERCADO_PAGO' ? (
              <PagoMercadoPagoPanel c={c} />
            ) : (
              <Visor comprobante={c} />
            )}
            <div className="grid gap-6">
              <Cotejo c={c} />
              <Resolucion c={c} />
            </div>
          </div>
          {c.estado === 'PENDIENTE_REVISION' && (
            <div className="grid items-start gap-6 lg:grid-cols-2">
              <AprobarPanel c={c} />
              <RechazarPanel c={c} />
            </div>
          )}
        </div>
      )}
    </>
  )
}
