import { Check, Circle } from 'lucide-react'

import type { PolicyCheck } from './passwordPolicy'

/** Requisitos de la contraseña nueva, tildados a medida que se cumplen. */
export function RequisitosClave({ checks }: { checks: PolicyCheck[] }) {
  return (
    <ul className="mt-1 grid gap-1 sm:grid-cols-2" aria-label="Requisitos de la contraseña">
      {checks.map((check) => (
        <li
          key={check.label}
          className={`flex items-center gap-1.5 ${check.ok ? 'text-success-700' : 'text-ink-muted'}`}
        >
          {check.ok ? (
            <Check aria-hidden="true" className="size-4" strokeWidth={2.5} />
          ) : (
            <Circle aria-hidden="true" className="size-3.5" strokeWidth={2} />
          )}
          <span>
            {check.label}
            <span className="sr-only">{check.ok ? ': cumplido' : ': pendiente'}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}
