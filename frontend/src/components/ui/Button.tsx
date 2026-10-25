import type { LucideIcon } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

const VARIANTS: Record<Variant, string> = {
  // Primario relleno: la acción que la Caja afirma, en petróleo (Regla del Sello).
  primary:
    'border border-brand-800 bg-brand-800 text-white hover:border-brand-700 hover:bg-brand-700 active:bg-brand-900',
  secondary:
    'border border-line-strong bg-surface text-brand-800 hover:border-brand-700 hover:bg-brand-50 active:bg-brand-100',
  danger:
    'border border-line-strong bg-surface text-danger-700 hover:border-danger-700 hover:bg-danger-50',
  ghost: 'border border-transparent bg-transparent text-brand-800 hover:bg-brand-50',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  icon?: LucideIcon
  busy?: boolean
  busyLabel?: string
  children: ReactNode
}

export function Button({
  variant = 'secondary',
  icon: Icon,
  busy = false,
  busyLabel,
  disabled,
  className = '',
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled ?? busy}
      aria-busy={busy || undefined}
      className={`inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-control px-4 text-sm font-semibold transition-colors duration-150 ease-out-quint disabled:cursor-not-allowed disabled:opacity-60 aria-busy:cursor-progress ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {Icon && (
        <Icon
          aria-hidden="true"
          className={`size-4 shrink-0 ${busy ? 'animate-spin' : ''}`}
          strokeWidth={2.25}
        />
      )}
      {busy && busyLabel ? busyLabel : children}
    </button>
  )
}
