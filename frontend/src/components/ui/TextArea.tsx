import { useId, type TextareaHTMLAttributes } from 'react'

interface TextAreaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'> {
  label: string
  hint?: string
  error?: string
}

export function TextArea({ label, hint, error, className = '', ...textarea }: TextAreaProps) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-sm font-medium text-ink">
        {label}
      </label>
      <textarea
        id={id}
        rows={3}
        aria-invalid={error ? true : undefined}
        aria-describedby={[hintId, errorId].filter(Boolean).join(' ') || undefined}
        className={`mt-1.5 block w-full rounded-control border bg-surface px-3 py-2.5 text-base text-ink placeholder:text-ink-subtle focus-visible:border-action-600 ${error ? 'border-danger-700' : 'border-line-strong'}`}
        {...textarea}
      />
      {hint && (
        <p id={hintId} className="mt-1.5 text-sm text-ink-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="mt-1.5 text-sm font-medium text-danger-700">
          {error}
        </p>
      )}
    </div>
  )
}
