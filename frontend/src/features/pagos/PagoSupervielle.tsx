import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Landmark, RefreshCw } from 'lucide-react'
import { useState } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { fetchPagosSupervielle, pagarConSupervielle, sincronizarPagoSPV } from './api'

const clavePagos = (boletaId: string) => ['pagos', 'supervielle', 'boleta', boletaId] as const

/**
 * Abre el link de pago del banco en otra pestaña: el botón Supervielle no vuelve solo a la Suite.
 * La pestaña se abre en el mismo clic (si se abriera al llegar la respuesta, el navegador la
 * bloquearía); si no se puede abrir, se va al banco en esta misma pestaña.
 */
export function BotonSupervielle({
  boletaId,
  onError,
}: {
  boletaId: string
  onError: (detalle: string | null) => void
}) {
  const queryClient = useQueryClient()
  const pago = useMutation({
    mutationFn: () => pagarConSupervielle(boletaId),
  })
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
            void queryClient.invalidateQueries({ queryKey: clavePagos(boletaId) })
          },
          onError: (e) => {
            pestana?.close()
            onError(toProblem(e).detail)
          },
        })
      }}
    >
      Pagar con Supervielle
    </Button>
  )
}

/**
 * Pago con Supervielle iniciado y todavía sin resolver: el escribano vuelve de la pestaña del
 * banco y pide verificar. La Suite consulta el pago al banco; nunca lo da por hecho.
 */
export function SeguimientoSupervielle({ boletaId, ddjjId }: { boletaId: string; ddjjId: string }) {
  const queryClient = useQueryClient()
  const [sinPago, setSinPago] = useState(false)
  const pagos = useQuery({
    queryKey: clavePagos(boletaId),
    queryFn: () => fetchPagosSupervielle(boletaId),
  })
  const ultimo = pagos.data?.[0]
  const verificar = useMutation({
    mutationFn: (pagoId: string) => sincronizarPagoSPV(pagoId),
    onSuccess: async (pago) => {
      setSinPago(pago.estado === 'CREADO')
      await queryClient.invalidateQueries({ queryKey: clavePagos(boletaId) })
      if (pago.estado !== 'CREADO') {
        await queryClient.invalidateQueries({ queryKey: ['ddjj', 'declaracion', ddjjId] })
      }
    },
  })
  if (!ultimo || (ultimo.estado !== 'CREADO' && ultimo.estado !== 'PENDIENTE')) return null

  const boton = (
    <Button
      icon={RefreshCw}
      busy={verificar.isPending}
      busyLabel="Consultando al banco…"
      onClick={() => {
        verificar.mutate(ultimo.id)
      }}
    >
      Ya pagué: verificar
    </Button>
  )
  return (
    <div className="mt-3 grid gap-3">
      {ultimo.estado === 'PENDIENTE' ? (
        <Alert tone="warning" title="Pago con Supervielle en proceso">
          El banco todavía no lo acreditó
          {ultimo.medio_pago ? ` (${ultimo.medio_pago})` : ''}. Cuando lo haga, entra a revisión de
          Tesorería. Podés volver a verificar más tarde.
        </Alert>
      ) : (
        <Alert tone="info" title="Link de pago de Supervielle generado">
          Pagá en la pestaña del banco. Cuando termines, verificá el pago acá: la Suite lo consulta
          al banco. Generado el {formatLocalDateTime(new Date(ultimo.created_at))}.
        </Alert>
      )}
      <div className="flex flex-wrap items-center gap-3">
        {boton}
        {sinPago && !verificar.isPending && (
          <p role="status" className="text-sm text-ink-muted">
            El banco todavía no informa un pago para esta boleta. Si recién pagaste, esperá unos
            minutos y volvé a verificar.
          </p>
        )}
      </div>
      {verificar.isError && <Alert tone="danger">{toProblem(verificar.error).detail}</Alert>}
    </div>
  )
}
