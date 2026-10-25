import type { ReactNode } from 'react'

interface PanelProps {
  title?: string
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  footer?: ReactNode
  className?: string
}

export function Panel({
  title,
  description,
  actions,
  children,
  footer,
  className = '',
}: PanelProps) {
  return (
    <section
      className={`overflow-hidden rounded-panel border border-line bg-surface shadow-panel ${className}`}
    >
      {(title || actions) && (
        <div className="flex flex-col gap-4 border-b border-line px-5 py-5 sm:flex-row sm:items-start sm:justify-between sm:px-6">
          <div className="min-w-0">
            {title && <h2 className="text-lg font-semibold text-ink">{title}</h2>}
            {description && (
              <div className="mt-1 max-w-[65ch] text-sm text-ink-muted">{description}</div>
            )}
          </div>
          {actions && <div className="flex shrink-0 flex-wrap gap-3">{actions}</div>}
        </div>
      )}
      {children}
      {footer && (
        <div className="border-t border-line bg-surface-sunken px-5 py-3 text-xs text-ink-muted sm:px-6">
          {footer}
        </div>
      )}
    </section>
  )
}

export function PageHeader({ title, description }: { title: string; description?: ReactNode }) {
  return (
    <div className="mb-8">
      <h1 className="text-2xl font-semibold tracking-tight text-brand-900 sm:text-[1.75rem]">
        {title}
      </h1>
      {description && <p className="mt-2 max-w-[65ch] text-ink-muted">{description}</p>}
    </div>
  )
}
