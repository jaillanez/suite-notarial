import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  CircleCheck,
  CircleX,
  HandCoins,
  Landmark,
  RefreshCw,
  Wallet,
} from 'lucide-react'
import { useState } from 'react'
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
import { formatPercent } from '../../lib/decimal'
import { useSession } from '../auth/session'
import { formatDate, todayIso } from '../padron/labels'
import { sincronizarPagoSPV } from '../pagos/api'
import { ESTADO_PAGO_MP, ESTADO_PAGO_SPV } from '../pagos/labels'
import {
  confirmarCobroMP,
  confirmarCobroSPV,
  fetchPrestamo,
  fetchSaldo,
  otorgar,
  pagarCuotaConMercadoPago,
  pagarCuotaConSupervielle,
  rechazar,
  registrarPago,
  type CobroCuotaMP,
  type CobroCuotaSPV,
  type PrestamoDetalle,
} from './api'
import { PlanCuotas } from './componentes'
import { Documentacion } from './Documentacion'
import { ESTADO_PRESTAMO, MONEDA, SISTEMA, importe } from './labels'
import { SaldoConjunto } from './SaldoConjunto'

function Dato({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-sm font-medium text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-ink tabular-nums">{children}</dd>
    </div>
  )
}

function useActualizar(id: string) {
  const queryClient = useQueryClient()
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['prestamos'] })
    await queryClient.invalidateQueries({ queryKey: ['prestamo', id] })
  }
}

function Resolver({ p }: { p: PrestamoDetalle }) {
  const actualizar = useActualizar(p.id)
  const [dialogo, setDialogo] = useState<'otorgar' | 'rechazar' | null>(null)
  const [motivo, setMotivo] = useState('')
  // La aprueba la Junta de Administración; acá se registra el acta (Caja, 24/11/2026).
  const [acta, setActa] = useState('')
  const [fechaJunta, setFechaJunta] = useState('')
  const accion = useMutation({
    mutationFn: () =>
      dialogo === 'otorgar'
        ? otorgar(p.id, { acta_junta: acta.trim(), fecha_junta: fechaJunta })
        : rechazar(p.id, motivo.trim()),
    onSuccess: async () => {
      setDialogo(null)
      await actualizar()
    },
  })
  const cerrar = () => {
    accion.reset()
    setDialogo(null)
  }
  return (
    <Panel
      title="Resolver la solicitud"
      description="La solicitud la aprueba o rechaza la Junta de Administración; acá se registra su decisión. Al otorgar se vuelven a verificar el tope de afectación, la mora y el garante con los datos de hoy, y se genera el plan de cuotas definitivo."
    >
      <div className="flex flex-wrap justify-end gap-3 px-5 py-4 sm:px-6">
        <Button
          variant="danger"
          icon={CircleX}
          onClick={() => {
            setDialogo('rechazar')
          }}
        >
          Rechazar
        </Button>
        <Button
          variant="primary"
          icon={CircleCheck}
          disabled={p.impedimentos_actuales.length > 0}
          onClick={() => {
            setDialogo('otorgar')
          }}
        >
          Registrar aprobación de la Junta
        </Button>
      </div>
      <Dialog
        open={dialogo !== null}
        onClose={cerrar}
        title={
          dialogo === 'otorgar'
            ? `Aprobación de la Junta · préstamo N° ${String(p.numero)}`
            : `Rechazar la solicitud N° ${String(p.numero)}`
        }
        description={
          dialogo === 'otorgar'
            ? 'Indicá el acta y la fecha de la reunión de la Junta que lo aprobó. Queda vigente con el plan de cuotas que se muestra; no se puede deshacer.'
            : 'El motivo queda registrado y lo ve el escribano.'
        }
        footer={
          <>
            <Button onClick={cerrar}>Cancelar</Button>
            {dialogo === 'otorgar' ? (
              <Button
                variant="primary"
                icon={CircleCheck}
                busy={accion.isPending}
                busyLabel="Otorgando…"
                disabled={!acta.trim() || !fechaJunta}
                onClick={() => {
                  accion.mutate()
                }}
              >
                Otorgar
              </Button>
            ) : (
              <Button
                variant="danger"
                icon={CircleX}
                busy={accion.isPending}
                busyLabel="Rechazando…"
                disabled={motivo.trim().length < 5}
                onClick={() => {
                  accion.mutate()
                }}
              >
                Rechazar
              </Button>
            )}
          </>
        }
      >
        <div className="grid gap-4">
          {accion.isError && <Alert tone="danger">{toProblem(accion.error).detail}</Alert>}
          {dialogo === 'otorgar' && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Acta de la Junta"
                placeholder="Por ejemplo: Acta 12/2026"
                value={acta}
                onChange={(e) => {
                  setActa(e.target.value)
                }}
              />
              <Field
                label="Fecha de la reunión"
                type="date"
                max={todayIso()}
                value={fechaJunta}
                onChange={(e) => {
                  setFechaJunta(e.target.value)
                }}
              />
            </div>
          )}
          {dialogo === 'otorgar' ? (
            <dl className="divide-y divide-line rounded-control border border-line">
              {[
                ['Escribano', p.escribano.apellido_nombre],
                ['Capital', importe(p.capital, p.moneda)],
                ['Cuotas', `${String(p.cuotas)} · ${SISTEMA[p.sistema].label.toLowerCase()}`],
                ['Primera cuota', importe(p.plan[0]?.cuota ?? null, p.moneda)],
                ['Total a devolver', importe(p.totales.total, p.moneda)],
              ].map(([label, valor]) => (
                <div key={label} className="flex justify-between gap-4 px-4 py-2.5 text-sm">
                  <dt className="text-ink-muted">{label}</dt>
                  <dd className="text-right font-semibold text-ink tabular-nums">{valor}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <TextArea
              label="Motivo del rechazo"
              hint="Obligatorio, al menos 5 caracteres."
              value={motivo}
              onChange={(e) => {
                setMotivo(e.target.value)
              }}
            />
          )}
        </div>
      </Dialog>
    </Panel>
  )
}

function Cobrar({ p }: { p: PrestamoDetalle }) {
  const actualizar = useActualizar(p.id)
  const proxima = p.plan.find((c) => c.estado === 'PENDIENTE')
  const [abierto, setAbierto] = useState(false)
  const [fecha, setFecha] = useState(todayIso())
  const pago = useMutation({
    mutationFn: () =>
      registrarPago(p.id, proxima?.numero ?? 0, {
        fecha_pago: fecha,
        importe: proxima?.cuota ?? '0',
      }),
    onSuccess: async () => {
      setAbierto(false)
      await actualizar()
    },
  })
  if (!proxima) return null
  return (
    <>
      <Button
        icon={HandCoins}
        onClick={() => {
          setAbierto(true)
        }}
      >
        Registrar pago de la cuota {proxima.numero}
      </Button>
      <Dialog
        open={abierto}
        onClose={() => {
          pago.reset()
          setAbierto(false)
        }}
        title={`Pago de la cuota ${String(proxima.numero)} de ${String(p.cuotas)}`}
        description={`Vence el ${formatDate(proxima.vencimiento)}. Las cuotas se cobran en orden.`}
        footer={
          <>
            <Button
              onClick={() => {
                setAbierto(false)
              }}
            >
              Cancelar
            </Button>
            <Button
              variant="primary"
              icon={HandCoins}
              busy={pago.isPending}
              busyLabel="Registrando…"
              disabled={!fecha}
              onClick={() => {
                pago.mutate()
              }}
            >
              Registrar {importe(proxima.cuota, p.moneda)}
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          {pago.isError && <Alert tone="danger">{toProblem(pago.error).detail}</Alert>}
          <Field
            label="Fecha del pago"
            type="date"
            className="[&_input]:tabular-nums"
            max={todayIso()}
            min={p.fecha_otorgamiento ?? undefined}
            value={fecha}
            onChange={(e) => {
              setFecha(e.target.value)
            }}
          />
          {fecha > proxima.vencimiento && (
            <Alert tone="warning">
              Se paga después del vencimiento. El interés punitorio todavía no está definido por la
              Caja: se registra la cuota del plan y el atraso queda en la auditoría.
            </Alert>
          )}
        </div>
      </Dialog>
    </>
  )
}

/** El escribano paga la próxima cuota en Mercado Pago y vuelve a la Suite, que consulta el pago. */
function PagarConMercadoPago({
  p,
  onError,
}: {
  p: PrestamoDetalle
  onError: (detalle: string | null) => void
}) {
  const proxima = p.plan.find((c) => c.estado === 'PENDIENTE')
  const pago = useMutation({
    mutationFn: () => pagarCuotaConMercadoPago(p.id),
    onSuccess: (url) => {
      window.location.assign(url)
    },
    onError: (e) => {
      onError(toProblem(e).detail)
    },
  })
  if (!proxima) return null
  return (
    <Button
      variant="primary"
      icon={Wallet}
      busy={pago.isPending}
      busyLabel="Abriendo Mercado Pago…"
      onClick={() => {
        onError(null)
        pago.mutate()
      }}
    >
      Pagar cuota {proxima.numero} con Mercado Pago
    </Button>
  )
}

/**
 * El escribano paga la próxima cuota (en pesos) con el botón Supervielle. El link del banco se
 * abre en otra pestaña en el mismo clic (si se abriera al llegar la respuesta, el navegador la
 * bloquearía): el botón no vuelve solo a la Suite, así que el escribano verifica el pago acá.
 */
function PagarConSupervielle({
  p,
  onError,
}: {
  p: PrestamoDetalle
  onError: (detalle: string | null) => void
}) {
  const actualizar = useActualizar(p.id)
  const proxima = p.plan.find((c) => c.estado === 'PENDIENTE')
  const pago = useMutation({ mutationFn: () => pagarCuotaConSupervielle(p.id) })
  if (!proxima) return null
  return (
    <Button
      variant="primary"
      icon={Landmark}
      busy={pago.isPending}
      busyLabel="Generando el link de pago…"
      onClick={() => {
        onError(null)
        const pestana = window.open('', '_blank')
        pago.mutate(undefined, {
          onSuccess: ({ url_pago }) => {
            if (pestana) {
              pestana.opener = null
              pestana.location.href = url_pago
            } else {
              window.location.assign(url_pago)
            }
            void actualizar()
          },
          onError: (e) => {
            pestana?.close()
            onError(toProblem(e).detail)
          },
        })
      }}
    >
      Pagar cuota {proxima.numero} con Supervielle
    </Button>
  )
}

/**
 * Deuda de la cuota publicada en Supervielle y todavía sin resolver: el escribano vuelve de la
 * pestaña del banco y pide verificar. La Suite consulta el pago al banco; nunca lo da por hecho.
 */
function SeguimientoSupervielle({ p, cobro }: { p: PrestamoDetalle; cobro: CobroCuotaSPV }) {
  const actualizar = useActualizar(p.id)
  const [sinPago, setSinPago] = useState(false)
  const verificar = useMutation({
    mutationFn: () => sincronizarPagoSPV(cobro.id),
    onSuccess: async (pago) => {
      setSinPago(pago.estado === 'CREADO')
      await actualizar()
    },
  })
  return (
    <div className="grid gap-3">
      {cobro.estado === 'PENDIENTE' ? (
        <Alert tone="warning" title={`Pago de la cuota ${String(cobro.cuota)} en proceso`}>
          Supervielle todavía no lo acreditó{cobro.medio_pago ? ` (${cobro.medio_pago})` : ''}.
          Cuando lo haga, Tesorería confirma el cobro y la cuota pasa a pagada. Podés volver a
          verificar más tarde.
        </Alert>
      ) : (
        <Alert
          tone="info"
          title={`Link de pago de Supervielle generado · cuota ${String(cobro.cuota)}`}
        >
          Pagá en la pestaña del banco. Cuando termines, verificá el pago acá: la Suite lo consulta
          al banco. Generado el {formatLocalDateTime(new Date(cobro.created_at))}.
        </Alert>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          icon={RefreshCw}
          busy={verificar.isPending}
          busyLabel="Consultando al banco…"
          onClick={() => {
            verificar.mutate()
          }}
        >
          Ya pagué: verificar
        </Button>
        {sinPago && !verificar.isPending && (
          <p role="status" className="text-sm text-ink-muted">
            El banco todavía no informa un pago para esta cuota. Si recién pagaste, esperá unos
            minutos y volvé a verificar.
          </p>
        )}
      </div>
      {verificar.isError && <Alert tone="danger">{toProblem(verificar.error).detail}</Alert>}
    </div>
  )
}

/** Pago de una cuota informado por un medio electrónico, a la espera de Tesorería. */
interface CobroPendiente {
  medio: 'MERCADO_PAGO' | 'SUPERVIELLE'
  id: string
  cuota: number
  importe_pagado: string | null
  /** Cuándo lo aprobó el medio de pago. */
  fecha: string | null
  medio_pago: string | null
}

const NOMBRE_MEDIO: Record<CobroPendiente['medio'], string> = {
  MERCADO_PAGO: 'Mercado Pago',
  SUPERVIELLE: 'Supervielle',
}

function cobroMP(c: CobroCuotaMP): CobroPendiente {
  return { ...c, medio: 'MERCADO_PAGO', fecha: c.aprobado_en }
}

function cobroSPV(c: CobroCuotaSPV): CobroPendiente {
  return { ...c, medio: 'SUPERVIELLE', fecha: c.pagado_en }
}

/** Pago aprobado (Mercado Pago o Supervielle): la cuota pasa a pagada cuando Tesorería lo confirma. */
function CobroAConfirmar({ p, cobro }: { p: PrestamoDetalle; cobro: CobroPendiente }) {
  const { can } = useSession()
  const actualizar = useActualizar(p.id)
  const [abierto, setAbierto] = useState(false)
  const cuota = p.plan.find((c) => c.numero === cobro.cuota)
  const nombre = NOMBRE_MEDIO[cobro.medio]
  const confirmar = useMutation({
    mutationFn: () =>
      cobro.medio === 'MERCADO_PAGO'
        ? confirmarCobroMP(p.id, cobro.id)
        : confirmarCobroSPV(p.id, cobro.id),
    onSuccess: async () => {
      setAbierto(false)
      await actualizar()
    },
  })
  const cerrar = () => {
    confirmar.reset()
    setAbierto(false)
  }
  const aprobado = cobro.fecha ? formatLocalDateTime(new Date(cobro.fecha)) : null
  if (!can('prestamos:cobrar')) {
    return (
      <Alert tone="info" title={`Pagaste la cuota ${String(cobro.cuota)} con ${nombre}`}>
        {nombre} aprobó el pago de{' '}
        <span className="whitespace-nowrap">{importe(cobro.importe_pagado, p.moneda)}</span>
        {aprobado && ` el ${aprobado}`}. Tesorería lo confirma y la cuota pasa a pagada.
      </Alert>
    )
  }
  const coincide = cuota !== undefined && cobro.importe_pagado === cuota.cuota
  return (
    <>
      <Alert
        tone="warning"
        title={`Pago con ${nombre} a confirmar · cuota ${String(cobro.cuota)}`}
        action={
          <Button
            variant="primary"
            icon={CircleCheck}
            onClick={() => {
              setAbierto(true)
            }}
          >
            Confirmar cobro de la cuota {cobro.cuota}
          </Button>
        }
      >
        {nombre} aprobó{' '}
        <span className="whitespace-nowrap">{importe(cobro.importe_pagado, p.moneda)}</span>
        {aprobado && ` el ${aprobado}`}
        {cobro.medio_pago && ` (${cobro.medio_pago})`}. La cuota sigue pendiente hasta que lo
        confirmes
        {cobro.medio === 'SUPERVIELLE' && ': antes, la Suite vuelve a consultar el pago al banco'}.
      </Alert>
      <Dialog
        open={abierto}
        onClose={cerrar}
        title={`Confirmar el cobro de la cuota ${String(cobro.cuota)} de ${String(p.cuotas)}`}
        description={`La cuota queda pagada con la fecha y el importe que informó ${nombre}. No se puede deshacer.`}
        footer={
          <>
            <Button onClick={cerrar}>Cancelar</Button>
            <Button
              variant="primary"
              icon={CircleCheck}
              busy={confirmar.isPending}
              busyLabel="Confirmando…"
              onClick={() => {
                confirmar.mutate()
              }}
            >
              Confirmar cobro
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          {confirmar.isError && <Alert tone="danger">{toProblem(confirmar.error).detail}</Alert>}
          <dl className="divide-y divide-line rounded-control border border-line">
            {[
              ['Escribano', p.escribano.apellido_nombre],
              ['Cuota del plan', importe(cuota?.cuota ?? null, p.moneda)],
              [`Pagado en ${nombre}`, importe(cobro.importe_pagado, p.moneda)],
              ['Aprobado', aprobado ?? '—'],
            ].map(([label, valor]) => (
              <div key={label} className="flex justify-between gap-4 px-4 py-2.5 text-sm">
                <dt className="text-ink-muted">{label}</dt>
                <dd className="text-right font-semibold text-ink tabular-nums">{valor}</dd>
              </div>
            ))}
          </dl>
          {!coincide && (
            <Alert tone="danger">
              El importe pagado no coincide con la cuota: no se puede confirmar.
            </Alert>
          )}
        </div>
      </Dialog>
    </>
  )
}

/** Todos los pagos con Mercado Pago informados para el préstamo. */
function CobrosMercadoPago({ p }: { p: PrestamoDetalle }) {
  return (
    <Panel title="Pagos con Mercado Pago">
      <ul className="divide-y divide-line">
        {p.cobros_mp.map((c) => (
          <li
            key={c.id}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 py-3 text-sm sm:px-6"
          >
            <span className="font-semibold text-ink tabular-nums">
              Cuota {c.cuota}
              <span className="ml-2 font-normal text-ink-muted">
                {c.aprobado_en ? formatLocalDateTime(new Date(c.aprobado_en)) : ''}
                {c.medio_pago && ` · ${c.medio_pago}`}
              </span>
            </span>
            <span className="flex items-baseline gap-3 tabular-nums">
              <span>{importe(c.importe_pagado, p.moneda)}</span>
              <span className="text-ink-muted">
                {c.confirmado_en && c.estado === 'approved'
                  ? 'Confirmado por Tesorería'
                  : c.a_confirmar
                    ? 'Aprobado · a confirmar'
                    : `${ESTADO_PAGO_MP[c.estado]}${c.confirmado_en ? ' después de confirmado' : ''}`}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

/** Pagos con Supervielle informados para el préstamo (sin los links que nadie pagó). */
function CobrosSupervielle({ p, cobros }: { p: PrestamoDetalle; cobros: CobroCuotaSPV[] }) {
  return (
    <Panel title="Pagos con Supervielle">
      <ul className="divide-y divide-line">
        {cobros.map((c) => (
          <li
            key={c.id}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 py-3 text-sm sm:px-6"
          >
            <span className="font-semibold text-ink tabular-nums">
              Cuota {c.cuota}
              <span className="ml-2 font-normal text-ink-muted">
                {c.pagado_en ? formatLocalDateTime(new Date(c.pagado_en)) : ''}
                {c.medio_pago && ` · ${c.medio_pago}`}
              </span>
            </span>
            <span className="flex items-baseline gap-3 tabular-nums">
              <span>{importe(c.importe_pagado, p.moneda)}</span>
              <span className="text-ink-muted">
                {c.confirmado_en && (c.estado === 'APROBADO' || c.estado === 'ACREDITADO')
                  ? 'Confirmado por Tesorería'
                  : c.a_confirmar
                    ? `${ESTADO_PAGO_SPV[c.estado]} · a confirmar`
                    : `${ESTADO_PAGO_SPV[c.estado]}${c.confirmado_en ? ' después de confirmado' : ''}`}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

export function PrestamoPage() {
  const { id = '' } = useParams()
  const { can } = useSession()
  const query = useQuery({ queryKey: ['prestamo', id], queryFn: () => fetchPrestamo(id) })
  const p = query.data
  const [errorPago, setErrorPago] = useState<string | null>(null)
  // El personal ve, junto al préstamo, todo lo que el escribano debe en préstamos.
  const personal = can('prestamos:read_all')
  // El de la próxima cuota: un pago de más sobre una cuota ya pagada lo ve Tesorería en el registro.
  const proxima = p?.plan.find((c) => c.estado === 'PENDIENTE')
  const mpAConfirmar = p?.cobros_mp.find((c) => c.a_confirmar && c.cuota === proxima?.numero)
  const spvAConfirmar = p?.cobros_spv.find((c) => c.a_confirmar && c.cuota === proxima?.numero)
  const aConfirmar = mpAConfirmar
    ? cobroMP(mpAConfirmar)
    : spvAConfirmar
      ? cobroSPV(spvAConfirmar)
      : undefined
  // La última deuda publicada en Supervielle para la próxima cuota, si el banco todavía no la
  // resolvió: el escribano verifica el pago al volver del banco.
  const ultimaSpv = p?.cobros_spv.find((c) => c.cuota === proxima?.numero)
  const spvAbierto =
    !aConfirmar &&
    !personal &&
    ultimaSpv !== undefined &&
    (ultimaSpv.estado === 'CREADO' || ultimaSpv.estado === 'PENDIENTE')
      ? ultimaSpv
      : undefined
  const pagosSpv = p?.cobros_spv.filter((c) => c.estado !== 'CREADO') ?? []
  const saldo = useQuery({
    queryKey: ['prestamos', 'saldo', p?.escribano.id],
    queryFn: () => fetchSaldo(p?.escribano.id),
    enabled: personal && p !== undefined,
  })
  const vigentes = saldo.data?.monedas.reduce((n, m) => n + m.prestamos_vigentes, 0) ?? 0
  // Si el único vigente es este, el panel repetiría lo que ya muestra la página.
  const mostrarSaldo = vigentes > (p?.estado === 'OTORGADO' ? 1 : 0)

  return (
    <>
      <Link
        to="/prestamos"
        className="mb-6 inline-flex min-h-11 items-center gap-2 text-sm font-medium"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Préstamos
      </Link>
      {query.isError && <Alert tone="danger">{toProblem(query.error).detail}</Alert>}
      {query.isPending && (
        <div aria-busy="true" className="grid gap-4">
          <span className="block h-9 w-72 animate-pulse rounded-control bg-brand-50" />
          <span className="block h-96 animate-pulse rounded-panel bg-brand-50" />
        </div>
      )}
      {p && (
        <div className="grid gap-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-brand-900 tabular-nums sm:text-[1.75rem]">
                Préstamo N° {p.numero}
              </h1>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <span className="text-ink-muted">{p.escribano.apellido_nombre}</span>
                <StatusIndicator
                  tone={ESTADO_PRESTAMO[p.estado].tone}
                  label={ESTADO_PRESTAMO[p.estado].label}
                />
              </div>
            </div>
            {p.estado === 'OTORGADO' && can('prestamos:cobrar') && !aConfirmar && <Cobrar p={p} />}
            {(p.puede_pagar_mp || (p.puede_pagar_spv && spvAbierto?.estado !== 'PENDIENTE')) && (
              <div className="flex flex-wrap gap-3">
                {p.puede_pagar_spv && spvAbierto?.estado !== 'PENDIENTE' && (
                  <PagarConSupervielle p={p} onError={setErrorPago} />
                )}
                {p.puede_pagar_mp && <PagarConMercadoPago p={p} onError={setErrorPago} />}
              </div>
            )}
          </div>

          {errorPago && <Alert tone="danger">{errorPago}</Alert>}

          {aConfirmar && <CobroAConfirmar p={p} cobro={aConfirmar} />}
          {spvAbierto && <SeguimientoSupervielle p={p} cobro={spvAbierto} />}

          {p.tasa_es_ejemplo && (
            <Alert tone="warning" title="Condiciones a confirmar">
              La tasa de esta línea es un valor de ejemplo, todavía no aprobado por el Directorio.
            </Alert>
          )}
          {p.estado === 'RECHAZADO' && p.motivo_rechazo && (
            <Alert tone="danger" title="Solicitud rechazada">
              {p.motivo_rechazo}
            </Alert>
          )}
          {p.estado === 'SOLICITADO' && p.impedimentos_actuales.length > 0 && (
            <Alert tone="danger" title="Hoy no se puede otorgar">
              <ul className="mt-1 grid list-disc gap-1 pl-5">
                {p.impedimentos_actuales.map((i) => (
                  <li key={i}>{i}</li>
                ))}
              </ul>
            </Alert>
          )}
          {p.estado === 'SOLICITADO' && p.avisos_actuales.length > 0 && (
            <Alert tone="warning" title="Para revisar antes de resolver">
              <ul className="mt-1 grid list-disc gap-1 pl-5">
                {p.avisos_actuales.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </Alert>
          )}
          {p.cuotas_vencidas > 0 && (
            <Alert
              tone="danger"
              title={`${String(p.cuotas_vencidas)} ${p.cuotas_vencidas === 1 ? 'cuota vencida' : 'cuotas vencidas'}`}
            >
              El préstamo tiene cuotas impagas después de su vencimiento.
              {aConfirmar &&
                proxima?.vencida &&
                ` La cuota ${String(aConfirmar.cuota)} ya está pagada con ${NOMBRE_MEDIO[aConfirmar.medio]}: deja de figurar vencida cuando Tesorería confirma el cobro.`}
            </Alert>
          )}

          <Panel title="Condiciones">
            <dl className="grid grid-cols-2 gap-4 px-5 py-4 sm:grid-cols-4 sm:px-6">
              <Dato label="Línea">{p.linea_nombre}</Dato>
              <Dato label="Moneda">{MONEDA[p.moneda].label}</Dato>
              <Dato label="Capital">{importe(p.capital, p.moneda)}</Dato>
              <Dato label="Plazo">{p.cuotas} cuotas</Dato>
              <Dato label="Tasa nominal anual">{formatPercent(p.tna)}</Dato>
              <Dato label="Sistema">{SISTEMA[p.sistema].label}</Dato>
              {p.ingreso_neto !== null && (
                <Dato label="Ingreso neto">{importe(p.ingreso_neto, p.moneda)}</Dato>
              )}
              {p.afectacion !== null && (
                <Dato label="Afectación">
                  {formatPercent(p.afectacion)} de {formatPercent(p.afectacion_maxima)}
                </Dato>
              )}
              <Dato label="Garante">{p.garante ? p.garante.apellido_nombre : 'Sin garante'}</Dato>
              <Dato label="Saldo de capital">{importe(p.saldo_capital, p.moneda)}</Dato>
              <Dato label="Otorgado">
                {p.fecha_otorgamiento ? formatDate(p.fecha_otorgamiento) : '—'}
              </Dato>
              {p.acta_junta && (
                <Dato label="Aprobó la Junta">
                  {p.acta_junta}
                  {p.fecha_junta ? ` · ${formatDate(p.fecha_junta)}` : ''}
                </Dato>
              )}
              <Dato label="Cargó">{p.creado_por ?? '—'}</Dato>
              <Dato label="Resolvió">
                {p.resuelto_por ?? '—'}
                {p.resuelto_en && (
                  <span className="block text-sm text-ink-muted">
                    {formatLocalDateTime(new Date(p.resuelto_en))}
                  </span>
                )}
              </Dato>
            </dl>
            {p.observaciones && (
              <p className="border-t border-line px-5 py-3 text-sm sm:px-6">
                <span className="font-medium text-ink-muted">Observaciones: </span>
                {p.observaciones}
              </p>
            )}
          </Panel>

          {(p.puede_cargar_documentos ||
            p.documentos.length > 0 ||
            p.documentacion_requerida.length > 0) && <Documentacion p={p} />}

          {saldo.data && mostrarSaldo && (
            <SaldoConjunto
              saldo={saldo.data}
              title={`Todos los préstamos de ${p.escribano.apellido_nombre}`}
              description="Préstamos vigentes en los que es titular, incluido este si está vigente."
            />
          )}

          {p.puede_resolver && <Resolver p={p} />}
          {p.estado === 'SOLICITADO' && !p.puede_resolver && can('prestamos:approve') && (
            <Alert tone="info">
              Cargaste esta solicitud: la resuelve otra persona (cuatro ojos).
            </Alert>
          )}

          <Panel
            title={p.estado === 'SOLICITADO' ? 'Plan de cuotas (proyectado)' : 'Plan de cuotas'}
            description={
              p.estado === 'SOLICITADO'
                ? 'Calculado como si se otorgara hoy; las fechas definitivas se fijan al otorgar.'
                : SISTEMA[p.sistema].ayuda
            }
          >
            <PlanCuotas
              plan={p.plan}
              totales={p.totales}
              conEstado={p.estado !== 'SOLICITADO' && p.estado !== 'RECHAZADO'}
              moneda={p.moneda}
            />
          </Panel>

          {p.cobros_mp.length > 0 && <CobrosMercadoPago p={p} />}
          {pagosSpv.length > 0 && <CobrosSupervielle p={p} cobros={pagosSpv} />}
        </div>
      )}
    </>
  )
}
