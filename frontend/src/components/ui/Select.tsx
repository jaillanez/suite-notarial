import { ChevronDown } from 'lucide-react'
import { useId, type SelectHTMLAttributes } from 'react'

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'> {
  label: string
  options: { value: string; label: string }[]
}

export function Select({ label, options, className = '', ...select }: SelectProps) {
  const id = useId()
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-sm font-medium text-ink">
        {label}
      </label>
      <div className="relative mt-1.5">
        <select
          id={id}
          className="block min-h-11 w-full cursor-pointer appearance-none rounded-control border border-line-strong bg-surface py-2 pr-10 pl-3 text-base text-ink focus-visible:border-action-600"
          {...select}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-ink-muted"
        />
      </div>
    </div>
  )
}
