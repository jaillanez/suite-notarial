import { ShieldCheck } from 'lucide-react'

import type { RoleInfo } from './api'

interface RoleCheckboxesProps {
  roles: RoleInfo[]
  selected: string[]
  onChange: (codes: string[]) => void
}

export function RoleCheckboxes({ roles, selected, onChange }: RoleCheckboxesProps) {
  return (
    <fieldset>
      <legend className="text-sm font-medium text-ink">Roles</legend>
      <div className="mt-2 divide-y divide-line rounded-control border border-line">
        {roles.map((role) => {
          const checked = selected.includes(role.code)
          return (
            <label
              key={role.code}
              className="flex cursor-pointer items-start gap-3 px-4 py-3 hover:bg-brand-50"
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => {
                  onChange(
                    checked ? selected.filter((c) => c !== role.code) : [...selected, role.code],
                  )
                }}
                className="mt-0.5 size-5 shrink-0 cursor-pointer accent-brand-800"
              />
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-x-2 text-sm font-semibold text-ink">
                  {role.name}
                  {role.mfa_required && (
                    <span className="inline-flex items-center gap-1 text-xs font-medium text-ink-muted">
                      <ShieldCheck aria-hidden="true" className="size-3.5" strokeWidth={2.25} />
                      Exige 2FA
                    </span>
                  )}
                </span>
                {role.description && (
                  <span className="mt-0.5 block text-sm text-ink-muted">{role.description}</span>
                )}
              </span>
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
