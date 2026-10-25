import { ChevronLeft, ChevronRight } from 'lucide-react'

interface PaginationProps {
  page: number
  pageSize: number
  total: number
  onPage: (page: number) => void
}

export function Pagination({ page, pageSize, total, onPage }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  const button =
    'inline-flex size-11 cursor-pointer items-center justify-center rounded-control border border-line-strong bg-surface text-brand-800 hover:border-brand-700 hover:bg-brand-50 disabled:cursor-not-allowed disabled:opacity-50'
  return (
    <nav
      aria-label="Paginación"
      className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface-sunken px-5 py-3 sm:px-6"
    >
      <p className="text-sm text-ink-muted tabular-nums" aria-live="polite">
        {total === 0 ? 'Sin resultados' : `${String(from)}–${String(to)} de ${String(total)}`}
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className={button}
          disabled={page <= 1}
          onClick={() => {
            onPage(page - 1)
          }}
          aria-label="Página anterior"
        >
          <ChevronLeft aria-hidden="true" className="size-5" />
        </button>
        <span className="min-w-20 text-center text-sm text-ink tabular-nums">
          {page} / {pages}
        </span>
        <button
          type="button"
          className={button}
          disabled={page >= pages}
          onClick={() => {
            onPage(page + 1)
          }}
          aria-label="Página siguiente"
        >
          <ChevronRight aria-hidden="true" className="size-5" />
        </button>
      </div>
    </nav>
  )
}
