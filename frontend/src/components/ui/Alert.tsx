import { CircleCheck, CircleX, Info, TriangleAlert, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

type Tone = 'success' | 'warning' | 'danger' | 'info'

const TONES: Record<Tone, { icon: LucideIcon; className: string }> = {
  success: { icon: CircleCheck, className: 'border-success-700/25 bg-success-50 text-success-700' },
  warning: {
    icon: TriangleAlert,
    className: 'border-warning-700/25 bg-warning-50 text-warning-700',
  },
  danger: { icon: CircleX, className: 'border-danger-700/25 bg-danger-50 text-danger-700' },
  info: { icon: Info, className: 'border-brand-100 bg-brand-50 text-brand-800' },
}

interface AlertProps {
  tone: Tone
  title?: string
  children: ReactNode
  action?: ReactNode
}

/** Mensaje de estado: ícono + texto sobre el par de tinte (Regla de la Pareja de Estado). */
export function Alert({ tone, title, children, action }: AlertProps) {
  const { icon: Icon, className } = TONES[tone]
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={`flex gap-3 rounded-control border px-4 py-3 ${className}`}
    >
      <Icon aria-hidden="true" className="mt-0.5 size-5 shrink-0" strokeWidth={2.25} />
      <div className="min-w-0 flex-1 text-sm">
        {title && <p className="font-semibold">{title}</p>}
        <div className={title ? 'mt-0.5' : ''}>{children}</div>
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  )
}
