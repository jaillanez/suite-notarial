import { CircleDashed, PenLine, Sparkles, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'

import { Alert } from '../../components/ui/Alert'
import type { AlertaIa, CampoSugerido } from './api'
import { nivelConfianza, textoConfianza } from './labels'

/** Lo que la persona tiene que saber antes de revisar: la Suite propone, la persona decide. */
export function AvisoHumano({ children }: { children: ReactNode }) {
  return (
    <Alert tone="info" title="Vos confirmás cada dato">
      {children}
    </Alert>
  )
}

export function AlertasSugerencia({ alertas }: { alertas: AlertaIa[] }) {
  if (alertas.length === 0) return null
  const ordenadas = [...alertas].sort((a, b) =>
    a.nivel === b.nivel ? 0 : a.nivel === 'ADVERTENCIA' ? -1 : 1,
  )
  return (
    <ul className="grid gap-3" aria-label="Alertas de la revisión">
      {ordenadas.map((a, i) => (
        <li key={`${a.codigo}-${String(i)}`}>
          <Alert tone={a.nivel === 'ADVERTENCIA' ? 'warning' : 'info'}>
            <p>{a.mensaje}</p>
            {a.evidencia && <Cita>{a.evidencia}</Cita>}
          </Alert>
        </li>
      ))}
    </ul>
  )
}

/** Fragmento del documento que respalda un dato (se muestra tal cual se leyó). */
export function Cita({ children }: { children: string }) {
  return (
    <blockquote className="mt-2 rounded-control border border-line bg-surface px-3 py-2 text-sm text-ink [overflow-wrap:anywhere]">
      {children}
    </blockquote>
  )
}

/**
 * Ayuda bajo cada campo del formulario: de dónde salió el valor, cuánta confianza tiene y si la
 * persona lo cambió. El texto lleva el significado; el ícono acompaña.
 */
export function PistaCampo({
  campo,
  actual,
  mostrar = (v) => v,
}: {
  campo: CampoSugerido | undefined
  actual: string
  mostrar?: (valor: string) => string
}): ReactNode {
  if (!campo) return undefined
  if (campo.valor === null) {
    return actual.trim() ? (
      <Pista icon={PenLine}>Lo completaste vos: la Suite no lo encontró en el documento.</Pista>
    ) : (
      <Pista icon={CircleDashed}>La Suite no lo encontró en el documento: completalo.</Pista>
    )
  }
  if (actual.trim() !== campo.valor) {
    return <Pista icon={PenLine}>Corregido. La Suite había sugerido {mostrar(campo.valor)}.</Pista>
  }
  const baja = nivelConfianza(campo.confianza) === 'baja'
  return (
    <Pista icon={baja ? TriangleAlert : Sparkles} tono={baja ? 'atencion' : undefined}>
      Sugerido por la Suite, {textoConfianza(campo.confianza)}
      {baja ? ': verificalo.' : '.'}
    </Pista>
  )
}

function Pista({
  icon: Icon,
  tono,
  children,
}: {
  icon: typeof Sparkles
  tono?: 'atencion'
  children: ReactNode
}) {
  return (
    <span className={`inline-flex gap-1.5 ${tono ? 'font-medium text-warning-700' : ''}`}>
      <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={2.25} />
      <span>{children}</span>
    </span>
  )
}

/** Respaldo de cada dato: valor, confianza, regla aplicada y fragmento del documento. */
export function Respaldo({
  campos,
  etiquetas,
  mostrar,
}: {
  campos: Record<string, CampoSugerido>
  etiquetas: Record<string, string>
  mostrar: (campo: string, valor: string) => string
}) {
  return (
    <dl className="divide-y divide-line">
      {Object.entries(etiquetas).map(([clave, etiqueta]) => {
        const campo = campos[clave]
        if (!campo) return null
        return (
          <div key={clave} className="px-5 py-4 sm:px-6">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <dt className="text-sm font-medium text-ink-muted">{etiqueta}</dt>
              <dd className="text-right font-semibold text-ink tabular-nums">
                {campo.valor === null ? (
                  <span className="font-normal text-ink-subtle">No encontrado</span>
                ) : (
                  mostrar(clave, campo.valor)
                )}
              </dd>
            </div>
            <p className="mt-1 text-sm text-ink-muted">
              {campo.regla}
              {campo.valor !== null && ` · ${textoConfianza(campo.confianza)}`}
            </p>
            {campo.evidencia && <Cita>{campo.evidencia}</Cita>}
          </div>
        )
      })}
    </dl>
  )
}

export function ConfirmacionHumana({
  checked,
  onChange,
  children,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  children: ReactNode
}) {
  return (
    <label className="flex min-h-11 cursor-pointer items-start gap-3 text-sm font-medium text-ink">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => {
          onChange(e.target.checked)
        }}
        className="mt-0.5 size-5 shrink-0 cursor-pointer accent-brand-800"
      />
      <span>{children}</span>
    </label>
  )
}
