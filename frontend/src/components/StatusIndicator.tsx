import { CircleCheck, CircleDashed, CircleX, TriangleAlert, type LucideIcon } from 'lucide-react'

export type Tone = 'success' | 'warning' | 'danger' | 'unknown'

const TONES: Record<Tone, { icon: LucideIcon; className: string }> = {
  success: { icon: CircleCheck, className: 'bg-success-50 text-success-700' },
  warning: { icon: TriangleAlert, className: 'bg-warning-50 text-warning-700' },
  danger: { icon: CircleX, className: 'bg-danger-50 text-danger-700' },
  unknown: { icon: CircleDashed, className: 'bg-surface-sunken text-ink-muted' },
}

interface StatusIndicatorProps {
  tone: Tone
  label: string
}

/** Estado con ícono + texto: el color nunca es el único portador del significado. */
export function StatusIndicator({ tone, label }: StatusIndicatorProps) {
  const { icon: Icon, className } = TONES[tone]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full py-1 pr-3 pl-2 text-sm font-semibold whitespace-nowrap ${className}`}
    >
      <Icon aria-hidden="true" className="size-4" strokeWidth={2.25} />
      {label}
    </span>
  )
}
