import { FileUp } from 'lucide-react'
import { useId } from 'react'

import { formatTamano } from '../../features/pagos/labels'

interface FileFieldProps {
  label: string
  accept: string
  /** Formatos y tamaño admitidos, en palabras ("PDF de hasta 25 MB"). */
  formatos: string
  archivo: File | null
  error?: string
  onChange: (file: File | null) => void
}

/** Zona de archivo: la etiqueta envuelve un `<input type="file">` accesible. */
export function FileField({ label, accept, formatos, archivo, error, onChange }: FileFieldProps) {
  const id = useId()
  return (
    <div>
      <span className="block text-sm font-medium text-ink">{label}</span>
      <label
        htmlFor={id}
        className={`mt-1.5 flex min-h-20 cursor-pointer items-center gap-3 rounded-control border border-dashed bg-surface-sunken px-4 py-3 transition-colors duration-150 ease-out-quint hover:border-brand-700 hover:bg-brand-50 has-[:focus-visible]:border-action-600 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-action-600 ${error ? 'border-danger-700' : 'border-line-strong'}`}
      >
        <FileUp aria-hidden="true" className="size-6 shrink-0 text-brand-800" strokeWidth={2} />
        <span className="min-w-0 text-sm">
          {archivo ? (
            <>
              <span className="block truncate font-semibold text-ink">{archivo.name}</span>
              <span className="block text-ink-muted tabular-nums">
                {formatTamano(archivo.size)} · Tocá para cambiarlo
              </span>
            </>
          ) : (
            <>
              <span className="block font-semibold text-brand-800">Elegí el archivo</span>
              <span className="block text-ink-muted">{formatos}</span>
            </>
          )}
        </span>
        <input
          id={id}
          type="file"
          accept={accept}
          className="sr-only"
          aria-label={label}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          onChange={(e) => {
            onChange(e.target.files?.[0] ?? null)
          }}
        />
      </label>
      {error && (
        <p id={`${id}-error`} className="mt-1.5 text-sm font-medium text-danger-700">
          {error}
        </p>
      )}
    </div>
  )
}
