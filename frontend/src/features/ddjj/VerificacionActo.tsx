import { CircleX, TriangleAlert } from 'lucide-react'

import { Alert } from '../../components/ui/Alert'
import { formatMoney } from '../../lib/decimal'
import type { ControlProtocolo, VerificacionActo } from './api'
import { CAMPO_DEL_CONTROL } from './verificacion'

/** Avisos del libro de protocolo como un globo pegado al campo que los provoca: la punta señala
 * el campo de arriba. Rojo si impide guardar, ámbar si solo hay que verificar. */
export function GloboControl({ controles }: { controles: ControlProtocolo[] }) {
  if (controles.length === 0) return null
  const bloquea = controles.some((c) => c.nivel === 'BLOQUEANTE')
  const tono = bloquea
    ? 'border-danger-700/25 bg-danger-50 text-danger-700'
    : 'border-warning-700/25 bg-warning-50 text-warning-700'
  return (
    <div role={bloquea ? 'alert' : 'status'} className="relative mt-3">
      <span
        aria-hidden="true"
        className={`absolute -top-[7px] left-5 size-3 rotate-45 border-t border-l ${tono}`}
      />
      <ul className={`grid gap-1.5 rounded-control border px-3 py-2.5 text-sm ${tono}`}>
        {controles.map((c) => {
          const Icono = c.nivel === 'BLOQUEANTE' ? CircleX : TriangleAlert
          return (
            <li key={c.codigo} className="flex items-start gap-2">
              <Icono aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={2.25} />
              {c.mensaje}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** Aporte estimado y avisos del libro de protocolo, bajo el formulario de un acto. Con
 * `avisosEnCampos`, los avisos de un campo van en su globo y aquí quedan solo los demás. */
export function ResultadoVerificacion({
  verificacion,
  actualizando,
  avisosEnCampos = false,
}: {
  verificacion: VerificacionActo | undefined
  actualizando: boolean
  avisosEnCampos?: boolean
}) {
  if (!verificacion) return null
  const { aporte } = verificacion
  const controles = avisosEnCampos
    ? verificacion.controles.filter((c) => !(c.codigo in CAMPO_DEL_CONTROL))
    : verificacion.controles
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
