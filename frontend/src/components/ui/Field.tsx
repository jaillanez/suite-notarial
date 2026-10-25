import { Eye, EyeOff } from 'lucide-react'
import { useId, useState, type InputHTMLAttributes, type ReactNode, type Ref } from 'react'

interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: string
  hint?: ReactNode
  error?: string
  trailing?: ReactNode
  ref?: Ref<HTMLInputElement>
}

const INPUT =
  'block min-h-11 w-full rounded-control border bg-surface px-3 text-base text-ink placeholder:text-ink-subtle transition-colors duration-150 ease-out-quint focus-visible:border-action-600 disabled:bg-surface-sunken disabled:text-ink-muted'

export function Field({ label, hint, error, trailing, className = '', ref, ...input }: FieldProps) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-sm font-medium text-ink">
        {label}
      </label>
      <div className="relative mt-1.5">
        <input
          ref={ref}
          id={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={[hintId, errorId].filter(Boolean).join(' ') || undefined}
          className={`${INPUT} ${error ? 'border-danger-700' : 'border-line-strong'} ${trailing ? 'pr-12' : ''}`}
          {...input}
        />
        {trailing && <div className="absolute inset-y-0 right-0 flex items-center">{trailing}</div>}
      </div>
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

type PasswordFieldProps = Omit<FieldProps, 'type' | 'trailing'>

export function PasswordField(props: PasswordFieldProps) {
  const [visible, setVisible] = useState(false)
  return (
    <Field
      {...props}
      type={visible ? 'text' : 'password'}
      trailing={
        <button
          type="button"
          onClick={() => {
            setVisible((v) => !v)
          }}
          aria-label={visible ? 'Ocultar contraseña' : 'Mostrar contraseña'}
          aria-pressed={visible}
          className="mr-1 inline-flex size-10 cursor-pointer items-center justify-center rounded-control text-ink-muted hover:bg-brand-50 hover:text-brand-800"
        >
          {visible ? (
            <EyeOff aria-hidden="true" className="size-5" strokeWidth={2} />
          ) : (
            <Eye aria-hidden="true" className="size-5" strokeWidth={2} />
          )}
        </button>
      }
    />
  )
}
