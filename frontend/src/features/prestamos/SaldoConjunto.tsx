import { Panel } from '../../components/ui/Panel'
import { formatDate } from '../padron/labels'
import type { SaldoConjunto as Saldo, SaldoMoneda } from './api'
import { MONEDA, importe } from './labels'

function Dato({
  label,
  children,
  detalle,
  alerta = false,
}: {
  label: string
  children: React.ReactNode
  detalle?: React.ReactNode
  alerta?: boolean
}) {
  return (
    <div>
      <dt className="text-sm font-medium text-ink-muted">{label}</dt>
      <dd
        className={`mt-0.5 text-lg font-semibold tabular-nums ${alerta ? 'text-danger-700' : 'text-ink'}`}
      >
        {children}
      </dd>
      {detalle && <dd className="text-sm text-ink-muted tabular-nums">{detalle}</dd>}
    </div>
  )
}

function plural(n: number, uno: string, varios: string): string {
  return `${String(n)} ${n === 1 ? uno : varios}`
}

function Moneda({ s, conTitulo }: { s: SaldoMoneda; conTitulo: boolean }) {
  return (
    <div className="px-5 py-4 sm:px-6">
      {conTitulo && (
        <h3 className="mb-3 text-sm font-semibold text-ink">{MONEDA[s.moneda].label}</h3>
      )}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-4 lg:grid-cols-4">
        <Dato
          label="Saldo de capital"
          detalle={plural(s.prestamos_vigentes, 'préstamo vigente', 'préstamos vigentes')}
        >
          {importe(s.saldo_capital, s.moneda)}
        </Dato>
        <Dato
          label="Falta pagar"
          detalle={`${plural(s.cuotas_pendientes, 'cuota', 'cuotas')}, con intereses`}
        >
          {importe(s.total_pendiente, s.moneda)}
        </Dato>
        <Dato
          label="Próximo vencimiento"
          detalle={s.proximo_vencimiento ? formatDate(s.proximo_vencimiento) : undefined}
        >
          {s.proximo_vencimiento ? importe(s.importe_proximo_vencimiento, s.moneda) : '—'}
        </Dato>
        <Dato
          label="Vencido impago"
          alerta={s.cuotas_vencidas > 0}
          detalle={s.cuotas_vencidas > 0 ? plural(s.cuotas_vencidas, 'cuota', 'cuotas') : 'Al día'}
        >
          {importe(s.importe_vencido, s.moneda)}
        </Dato>
      </dl>
    </div>
  )
}

/** Saldo del conjunto de préstamos vigentes, una fila por moneda (nunca se suman). */
export function SaldoConjunto({
  saldo,
  title,
  description,
}: {
  saldo: Saldo
  title: string
  description?: string
}) {
  const pendientes = saldo.solicitudes_pendientes
  return (
    <Panel
      title={title}
      description={description}
      footer={
        pendientes > 0
          ? `Además, ${plural(pendientes, 'solicitud pendiente', 'solicitudes pendientes')} de resolver: no suman hasta que se otorgan.`
          : undefined
      }
    >
      <div className="divide-y divide-line">
        {saldo.monedas.map((s) => (
          <Moneda key={s.moneda} s={s} conTitulo={saldo.monedas.length > 1} />
        ))}
      </div>
    </Panel>
  )
}
