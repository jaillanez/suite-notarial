import { useMutation, useQueryClient } from '@tanstack/react-query'
import { LogOut, Menu, ShieldCheck, X } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router'

import { logout } from '../features/auth/api'
import { SESSION_KEY, needsMfaEnrollment, useSession } from '../features/auth/session'
import { BrandLogo } from './BrandLogo'

interface NavItem {
  to: string
  label: string
  /** Alcanza con uno de los permisos. */
  permission?: string | string[]
}

const NAV: NavItem[] = [
  { to: '/', label: 'Inicio' },
  {
    to: '/ddjj',
    label: 'Declaraciones juradas',
    permission: ['ddjj:read_own', 'ddjj:read_all', 'ddjj:approve'],
  },
  { to: '/tesoreria/conciliacion', label: 'Conciliación', permission: 'comprobantes:verify' },
  { to: '/padron/escribanos', label: 'Escribanos', permission: 'escribanos:read' },
  { to: '/padron/registros', label: 'Registros', permission: 'escribanos:read' },
  { to: '/parametros', label: 'Parámetros', permission: 'parameters:read' },
  {
    to: '/reportes',
    label: 'Reportes',
    permission: ['reports:financial', 'audit:read', 'escribanos:read'],
  },
  { to: '/cms', label: 'Sitio', permission: 'cms:publish' },
  { to: '/usuarios', label: 'Usuarios', permission: 'users:read' },
  { to: '/auditoria', label: 'Auditoría', permission: 'audit:read' },
  { to: '/estado', label: 'Estado del sistema' },
]

function navClass({ isActive }: { isActive: boolean }): string {
  return `flex min-h-11 items-center rounded-control px-3 text-sm font-medium transition-colors duration-150 ease-out-quint ${
    isActive
      ? 'bg-brand-50 text-brand-900'
      : 'text-ink-muted hover:bg-brand-50 hover:text-brand-800'
  }`
}

export function AppShell() {
  const { user, can } = useSession()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.clear()
      queryClient.setQueryData(SESSION_KEY, null)
      void navigate('/ingresar', { replace: true })
    },
  })

  // Mientras falte el 2FA obligatorio, el backend rechaza todo lo demás: no se ofrece.
  const locked = user ? needsMfaEnrollment(user) : false
  const items = locked
    ? []
    : NAV.filter((item) => !item.permission || [item.permission].flat().some((p) => can(p)))
  const navLinks = items.map((item) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.to === '/'}
      className={navClass}
      onClick={() => {
        setMenuOpen(false)
      }}
    >
      {item.label}
    </NavLink>
  ))

  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-[4.5rem] max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
          <BrandLogo />
          <div className="flex items-center gap-1">
            <NavLink
              to="/cuenta/seguridad"
              className={({ isActive }) =>
                `hidden min-h-11 items-center gap-2 rounded-control px-3 text-left sm:flex ${
                  isActive ? 'bg-brand-50' : 'hover:bg-brand-50'
                }`
              }
            >
              <span className="flex flex-col leading-tight">
                <span className="text-sm font-semibold text-ink">{user?.full_name}</span>
                <span className="text-xs text-ink-muted">Seguridad de la cuenta</span>
              </span>
            </NavLink>
            <button
              type="button"
              onClick={() => {
                signOut.mutate()
              }}
              disabled={signOut.isPending}
              className="hidden min-h-11 cursor-pointer items-center gap-2 rounded-control px-3 text-sm font-semibold text-brand-800 hover:bg-brand-50 disabled:opacity-60 sm:inline-flex"
            >
              <LogOut aria-hidden="true" className="size-4" strokeWidth={2.25} />
              Cerrar sesión
            </button>
            <button
              type="button"
              aria-expanded={menuOpen}
              aria-controls="menu-principal"
              aria-label={menuOpen ? 'Cerrar menú' : 'Abrir menú'}
              onClick={() => {
                setMenuOpen((v) => !v)
              }}
              className="inline-flex size-11 cursor-pointer items-center justify-center rounded-control text-brand-800 hover:bg-brand-50 sm:hidden"
            >
              {menuOpen ? (
                <X aria-hidden="true" className="size-5" />
              ) : (
                <Menu aria-hidden="true" className="size-5" />
              )}
            </button>
          </div>
        </div>
        {items.length > 0 && (
          <nav
            aria-label="Principal"
            className="mx-auto hidden max-w-5xl gap-1 px-4 pb-2 sm:flex sm:px-6"
          >
            {navLinks}
          </nav>
        )}
        {menuOpen && (
          <nav
            id="menu-principal"
            aria-label="Principal"
            className="flex flex-col gap-1 border-t border-line px-4 py-3 sm:hidden"
          >
            {navLinks}
            <NavLink
              to="/cuenta/seguridad"
              className={navClass}
              onClick={() => {
                setMenuOpen(false)
              }}
            >
              <ShieldCheck aria-hidden="true" className="mr-2 size-4" strokeWidth={2.25} />
              Seguridad de la cuenta
            </NavLink>
            <button
              type="button"
              onClick={() => {
                signOut.mutate()
              }}
              className="flex min-h-11 cursor-pointer items-center gap-2 rounded-control px-3 text-left text-sm font-semibold text-brand-800 hover:bg-brand-50"
            >
              <LogOut aria-hidden="true" className="size-4" strokeWidth={2.25} />
              Cerrar sesión de {user?.full_name}
            </button>
          </nav>
        )}
      </header>
      <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
        <Outlet />
      </main>
    </div>
  )
}

export function PublicShell() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-[4.5rem] max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
          <BrandLogo to="/ingresar" />
          <p className="text-sm font-medium text-ink-muted">Suite Notarial</p>
        </div>
      </header>
      <main className="flex flex-1 justify-center px-4 py-10 sm:px-6 sm:py-16">
        <div className="w-full max-w-md">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
