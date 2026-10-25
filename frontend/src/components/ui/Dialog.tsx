import { X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode } from 'react'

interface DialogProps {
  open: boolean
  title: string
  description?: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
}

/**
 * Diálogo modal nativo (`<dialog>` + `showModal`): foco atrapado, Escape y `inert` del fondo
 * los resuelve el navegador.
 */
export function Dialog({ open, title, description, onClose, children, footer }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      dialog.showModal()
      // El foco va al primer campo editable, no al botón de cerrar.
      bodyRef.current
        ?.querySelector<HTMLElement>('input:not([disabled]), select, textarea')
        ?.focus()
    }
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      onClose={onClose}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-panel border border-line bg-surface p-0 text-ink shadow-panel backdrop:bg-brand-950/40"
    >
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4 sm:px-6">
        <div>
          <h2 id={titleId} className="text-lg font-semibold text-ink">
            {title}
          </h2>
          {description && (
            <p id={descriptionId} className="mt-1 text-sm text-ink-muted">
              {description}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Cerrar"
          className="-mr-2 inline-flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-control text-ink-muted hover:bg-brand-50 hover:text-brand-800"
        >
          <X aria-hidden="true" className="size-5" strokeWidth={2} />
        </button>
      </div>
      <div ref={bodyRef} className="px-5 py-5 sm:px-6">
        {children}
      </div>
      {footer && (
        <div className="flex flex-col-reverse gap-3 border-t border-line bg-surface-sunken px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
          {footer}
        </div>
      )}
    </dialog>
  )
}
