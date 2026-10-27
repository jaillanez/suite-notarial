import { Alert } from '../../components/ui/Alert'
import { formatMoney } from '../../lib/decimal'
import type { VerificacionActo } from './api'

/** Aporte estimado y avisos del libro de protocolo, bajo el formulario de un acto. */
export function ResultadoVerificacion({
  verificacion,
  actualizando,
}: {
  verificacion: VerificacionActo | undefined
  actualizando: boolean
}) {
  if (!verificacion) return null
  const { aporte, controles } = verificacion
  if (aporte === null && controles.length === 0) return null
  return (
    <div className="grid gap-3" aria-live="polite" aria-busy={actualizando}>
      {aporte !== null && (
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 rounded-control bg-surface-sunken px-4 py-3">
          <span className="text-sm text-ink-muted">
            Aporte estimado con los parámetros del período
          </span>
          <span
            className={`font-semibold text-ink tabular-nums transition-opacity duration-150 ${actualizando ? 'opacity-60' : ''}`}
          >
            {formatMoney(aporte)}
          </span>
        </div>
      )}
      {controles.map((c) => (
        <Alert key={c.codigo} tone={c.nivel === 'BLOQUEANTE' ? 'danger' : 'warning'}>
          {c.mensaje}
        </Alert>
      ))}
    </div>
  )
}
