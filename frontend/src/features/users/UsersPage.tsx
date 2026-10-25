import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Search, UserPlus } from 'lucide-react'
import { useDeferredValue, useState } from 'react'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { Pagination } from '../../components/ui/Pagination'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { roleLabel } from '../auth/roles'
import { useSession } from '../auth/session'
import { fetchRoles, fetchUsers, type UserFilters, type UserRow } from './api'
import { CreateUserDialog, RolesDialog, StatusDialog } from './UserDialogs'

const PAGE_SIZE = 20

interface RowActionsProps {
  row: UserRow
  canManageRoles: boolean
  canSuspend: boolean
  onRoles: (row: UserRow) => void
  onStatus: (row: UserRow) => void
}

function RowActions({ row, canManageRoles, canSuspend, onRoles, onStatus }: RowActionsProps) {
  return (
    <div className="flex justify-end gap-1">
      {canManageRoles && (
        <Button
          variant="ghost"
          onClick={() => {
            onRoles(row)
          }}
        >
          Roles
        </Button>
      )}
      {canSuspend && (
        <Button
          variant="ghost"
          className={row.is_active ? 'text-danger-700 hover:bg-danger-50' : ''}
          onClick={() => {
            onStatus(row)
          }}
        >
          {row.is_active ? 'Suspender' : 'Reactivar'}
        </Button>
      )}
    </div>
  )
}

function UserStatus({ row }: { row: UserRow }) {
  return row.is_active ? (
    <StatusIndicator tone="success" label="Activa" />
  ) : (
    <span title={row.suspension_reason ?? undefined}>
      <StatusIndicator tone="danger" label="Suspendida" />
    </span>
  )
}

export function UsersPage() {
  const { user: me, can } = useSession()
  const [filters, setFilters] = useState<UserFilters>({
    page: 1,
    pageSize: PAGE_SIZE,
    q: '',
    status: 'all',
  })
  const deferredQ = useDeferredValue(filters.q)
  const query = useQuery({
    queryKey: ['users', { ...filters, q: deferredQ }],
    queryFn: () => fetchUsers({ ...filters, q: deferredQ }),
    placeholderData: keepPreviousData,
  })
  const roles = useQuery({ queryKey: ['roles'], queryFn: fetchRoles, staleTime: 300_000 })
  const [creating, setCreating] = useState(false)
  const [statusTarget, setStatusTarget] = useState<UserRow | null>(null)
  const [rolesTarget, setRolesTarget] = useState<UserRow | null>(null)

  const rows = query.data?.items ?? []
  const actionProps = (row: UserRow): RowActionsProps => ({
    row,
    canManageRoles: can('roles:manage'),
    canSuspend: can('users:suspend') && row.id !== me?.id,
    onRoles: setRolesTarget,
    onStatus: setStatusTarget,
  })
  const emptyMessage =
    filters.q || filters.status !== 'all'
      ? 'Ningún usuario coincide con la búsqueda. Probá con otro nombre, correo o CUIT.'
      : 'Todavía no hay usuarios cargados.'

  return (
    <>
      <PageHeader
        title="Usuarios"
        description="Cuentas con acceso a la Suite. Las cuentas no se borran: se suspenden con un motivo que queda en la auditoría."
      />
      <Panel
        title="Listado"
        actions={
          can('users:write') ? (
            <Button
              variant="primary"
              icon={UserPlus}
              onClick={() => {
                setCreating(true)
              }}
            >
              Nuevo usuario
            </Button>
          ) : undefined
        }
      >
        <div className="grid gap-4 border-b border-line px-5 py-4 sm:grid-cols-[1fr_14rem] sm:px-6">
          <Field
            label="Buscar"
            type="search"
            placeholder="Nombre, correo o CUIT"
            value={filters.q}
            onChange={(e) => {
              setFilters((f) => ({ ...f, q: e.target.value, page: 1 }))
            }}
            trailing={
              <Search
                aria-hidden="true"
                className="mr-3 size-4 text-ink-subtle"
                strokeWidth={2.25}
              />
            }
          />
          <Select
            label="Estado"
            value={filters.status}
            onChange={(e) => {
              setFilters((f) => ({
                ...f,
                status: e.target.value as UserFilters['status'],
                page: 1,
              }))
            }}
            options={[
              { value: 'all', label: 'Todas' },
              { value: 'active', label: 'Activas' },
              { value: 'suspended', label: 'Suspendidas' },
            ]}
          />
        </div>

        {query.isError && (
          <div className="px-5 py-4 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}

        {/* Celular: lista apilada. Desde 640px: tabla con cabecera fija. */}
        <ul className="divide-y divide-line sm:hidden" aria-busy={query.isFetching}>
          {query.isPending &&
            Array.from({ length: 4 }, (_, i) => (
              <li key={i} className="px-5 py-4">
                <span className="block h-12 w-full animate-pulse rounded-control bg-brand-50" />
              </li>
            ))}
          {!query.isPending && rows.length === 0 && (
            <li className="px-5 py-10 text-center text-ink-muted">{emptyMessage}</li>
          )}
          {rows.map((row) => (
            <li key={row.id} className="px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold text-ink">{row.full_name}</p>
                  <p className="text-sm break-all text-ink-muted">{row.email}</p>
                </div>
                <UserStatus row={row} />
              </div>
              <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                <dt className="text-ink-muted">CUIT</dt>
                <dd className="text-ink tabular-nums">{row.cuit}</dd>
                <dt className="text-ink-muted">Roles</dt>
                <dd className="text-ink">{row.roles.map(roleLabel).join(', ') || 'Sin roles'}</dd>
              </dl>
              <div className="-mx-3 mt-2">
                <RowActions {...actionProps(row)} />
              </div>
            </li>
          ))}
        </ul>

        <div className="hidden max-h-[36rem] overflow-auto sm:block" aria-busy={query.isFetching}>
          <table className="w-full min-w-[44rem] border-collapse text-left text-sm">
            <caption className="sr-only">Usuarios de la Suite Notarial</caption>
            <thead className="sticky top-0 z-10 bg-surface-sunken text-xs font-semibold text-ink-muted">
              <tr className="border-b border-line">
                <th scope="col" className="px-5 py-3 sm:px-6">
                  Persona
                </th>
                <th scope="col" className="px-3 py-3">
                  CUIT
                </th>
                <th scope="col" className="px-3 py-3">
                  Roles
                </th>
                <th scope="col" className="px-3 py-3">
                  Estado
                </th>
                <th scope="col" className="px-3 py-3">
                  Último ingreso
                </th>
                <th scope="col" className="px-5 py-3 text-right sm:px-6">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {query.isPending &&
                Array.from({ length: 5 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={6} className="px-5 py-4 sm:px-6">
                      <span className="block h-5 w-full animate-pulse rounded-control bg-brand-50" />
                    </td>
                  </tr>
                ))}
              {!query.isPending && rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-10 text-center text-ink-muted sm:px-6">
                    {emptyMessage}
                  </td>
                </tr>
              )}
              {rows.map((row) => (
                <tr key={row.id} className="align-top">
                  <td className="px-5 py-3 sm:px-6">
                    <span className="block font-semibold text-ink">{row.full_name}</span>
                    <span className="block text-ink-muted">{row.email}</span>
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-ink tabular-nums">{row.cuit}</td>
                  <td className="px-3 py-3 text-ink">
                    {row.roles.map(roleLabel).join(', ') || (
                      <span className="text-ink-subtle">Sin roles</span>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    <UserStatus row={row} />
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-ink-muted tabular-nums">
                    {row.last_login_at ? formatLocalDateTime(new Date(row.last_login_at)) : 'Nunca'}
                  </td>
                  <td className="px-5 py-2 text-right whitespace-nowrap sm:px-6">
                    <RowActions {...actionProps(row)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination
          page={filters.page}
          pageSize={filters.pageSize}
          total={query.data?.total ?? 0}
          onPage={(page) => {
            setFilters((f) => ({ ...f, page }))
          }}
        />
      </Panel>

      <CreateUserDialog
        open={creating}
        roles={roles.data ?? []}
        onClose={() => {
          setCreating(false)
        }}
      />
      <StatusDialog
        user={statusTarget}
        onClose={() => {
          setStatusTarget(null)
        }}
      />
      <RolesDialog
        key={rolesTarget?.id ?? 'none'}
        user={rolesTarget}
        roles={roles.data ?? []}
        onClose={() => {
          setRolesTarget(null)
        }}
      />
    </>
  )
}
