import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { formatMoney } from '../../lib/decimal'
import { fetchBoleta } from '../ddjj/api'
import { sincronizarPagoMP, type PagoMercadoPago } from './api'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const EN_CURSO = new Set(['CREADO', 'pending', 'authorized', 'in_process', 'in_mediation'])

function Resultado({ pago }: { pago: PagoMercadoPago }) {
  if (pago.estado === 'approved') {
    return (
      <Alert tone="success" title="Mercado Pago aprobó tu pago">
        Pagaste {formatMoney(pago.importe_pagado)}. Tesorería lo confirma y la boleta pasa a pagada;
        mientras tanto la vas a ver como «Pago con Mercado Pago en revisión».
      </Alert>
    )
  }
  if (pago.estado === 'CREADO') {
    return (
      <Alert tone="info" title="Todavía no hay un pago registrado">
        Si completaste el pago en Mercado Pago, puede tardar unos minutos en aparecer: consultá de
        nuevo en un rato.
      </Alert>
    )
  }
  if (EN_CURSO.has(pago.estado)) {
    return (
      <Alert tone="info" title="El pago está en proceso">
        Mercado Pago todavía no lo acreditó. Cuando lo haga, lo vas a ver en la boleta.
      </Alert>
    )
  }
  return (
    <Alert tone="warning" title="Mercado Pago no aprobó el pago">
      No se cobró nada. Podés intentar de nuevo desde la boleta, con otro medio de pago, o pagar por
      transferencia y adjuntar el comprobante.
    </Alert>
  )
}

/** Vuelta desde Mercado Pago: la Suite consulta el pago a Mercado Pago (no a la dirección). */
export function RetornoMercadoPagoPage() {
  const [params] = useSearchParams()
  // Solo un UUID: el valor viene de la URL de vuelta y termina en la ruta de un POST.
  const crudo = params.get('pago') ?? ''
  const pagoId = UUID.test(crudo) ? crudo : ''
  const consulta = useQuery({
    queryKey: ['pagos', 'mercadopago', 'retorno', pagoId],
    queryFn: () => sincronizarPagoMP(pagoId),
    enabled: pagoId !== '',
    retry: false,
  })
  const boleta = useQuery({
    queryKey: ['ddjj', 'boleta', consulta.data?.boleta_id],
    queryFn: () => fetchBoleta(consulta.data?.boleta_id ?? ''),
    enabled: Boolean(consulta.data?.boleta_id),
  })
  const volver = boleta.data ? `/ddjj/${boleta.data.ddjj_id}` : '/ddjj'

  return (
    <>
      <PageHeader
        title="Pago con Mercado Pago"
        description="Consultamos el resultado directamente a Mercado Pago."
      />
      <Panel>
        <div className="grid gap-5 px-5 py-6 sm:px-6">
          {!pagoId && (
            <Alert tone="danger">
              El enlace de vuelta no tiene un identificador de pago válido.
            </Alert>
          )}
          {consulta.isPending && pagoId && (
            <p className="text-ink-muted" aria-live="polite" aria-busy="true">
              Consultando el pago a Mercado Pago…
            </p>
          )}
          {consulta.isError && <Alert tone="danger">{toProblem(consulta.error).detail}</Alert>}
          {consulta.data && <Resultado pago={consulta.data} />}
          {boleta.data && (
            <p className="text-sm text-ink-muted tabular-nums">
              Boleta N° {boleta.data.numero} · total {formatMoney(boleta.data.total_a_pagar)}
            </p>
          )}
          <div className="flex flex-wrap gap-3">
            <Link
              to={volver}
              className="inline-flex min-h-11 items-center gap-2 rounded-control border border-line-strong bg-surface px-4 text-sm font-semibold text-brand-800 no-underline hover:border-brand-700 hover:bg-brand-50"
            >
              <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
              Volver a la declaración
            </Link>
            {consulta.data && consulta.data.estado !== 'approved' && (
              <Button
                icon={RefreshCw}
                busy={consulta.isFetching}
                busyLabel="Consultando…"
                onClick={() => {
                  void consulta.refetch()
                }}
              >
                Consultar de nuevo
              </Button>
            )}
          </div>
        </div>
      </Panel>
    </>
  )
}
