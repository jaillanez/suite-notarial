import { notifyManager, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, LogOut, Menu, ShieldCheck, X } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router'

import { logout } from '../features/auth/api'
import {
  SESSION_KEY,
  clearUserData,
  mfaSugeridoPendiente,
  needsMfaEnrollment,
  omitirMfaSugerido,
  useSession,
} from '../features/auth/session'
import { Alert } from './ui/Alert'
import { BrandLogo } from './BrandLogo'

interface NavItem {
  to: string
  label: string
  /** Alcanza con uno de los permisos. */
  permission?: string | string[]
  /** Nombre para el personal de la Caja, cuando la misma pantalla cumple otra función. */
  staffLabel?: string
}

const NAV: NavItem[] = [
  { to: '/', label: 'Inicio' },
  {
    to: '/ddjj',
    label: 'Declaraciones juradas',
    staffLabel: 'DDJJ recibidas',
    permission: ['ddjj:read_own', 'ddjj:read_all', 'ddjj:approve'],
  },
  {
    to: '/a-cargo',
    label: 'Escribano a cargo',
    staffLabel: 'Designaciones a cargo',
    permission: ['escribanos:read', 'ddjj:create_own'],
  },
  { to: '/tesoreria/conciliacion', label: 'Conciliación', permission: 'comprobantes:verify' },
  { to: '/padron/escribanos', label: 'Escribanos', permission: 'escribanos:read' },
  { to: '/padron/registros', label: 'Registros', permission: 'escribanos:read' },
  { to: '/parametros', label: 'Parámetros', permission: 'parameters:read' },
  {
    to: '/reportes',
    label: 'Reportes',
    permission: ['reports:financial', 'audit:read', 'escribanos:read', 'puntos:read_all'],
  },
  {
    to: '/prestamos',
    label: 'Préstamos',
    permission: ['prestamos:read_own', 'prestamos:read_all', 'prestamos:manage'],
  },
  { to: '/reportes/MIS_APORTES', label: 'Mis aportes', permission: 'boletas:read_own' },
  {
    to: '/reportes/MIS_ACTOS_HISTORICOS',
    label: 'Actos anteriores',
    permission: 'ddjj:read_own',
  },
  { to: '/mis-puntos', label: 'Mis puntos', permission: 'puntos:read_own' },
  { to: '/previsional/puntos', label: 'Aportes y puntos', permission: 'puntos:read_all' },
  { to: '/cms', label: 'Sitio', permission: 'cms:publish' },
  { to: '/migracion', label: 'Migración', permission: 'migracion:read' },
  { to: '/usuarios', label: 'Usuarios', permission: 'users:read' },
  { to: '/auditoria', label: 'Auditoría', permission: 'audit:read' },
  { to: '/estado', label: 'Estado del sistema' },
]

function navClass({ isActive }: { isActive: boolean }): string {
  return `flex min-h-11 items-center rounded-control px-3 text-sm font-medium whitespace-nowrap transition-colors duration-150 ease-out-quint ${
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
  const location = useLocation()
  // Recomendación de 2FA: un aviso que no bloquea; «Ahora no» lo oculta hasta cerrar la pestaña.
  const [, setOmitido] = useState(false)
  const sugerir2fa =
    user !== null && mfaSugeridoPendiente(user) && location.pathname !== '/cuenta/seguridad'
  // El personal de la Caja ve las pantallas compartidas con su nombre de administración.
  const personal = can('ddjj:read_all') || can('ddjj:approve')
  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      // Primero la sesión en null (la observa el SessionProvider): si se borrara la caché antes,
      // el observador seguiría con el usuario viejo y el ingreso devolvería al inicio.
      queryClient.setQueryData(SESSION_KEY, null)
      // Tampoco quedan en memoria las mutaciones de la sesión (pueden llevar datos sensibles).
      clearUserData(queryClient)
      // React Query avisa a los observadores en una tarea posterior: navegar en la misma tanda
      // hace que la pantalla de ingreso se dibuje ya sin usuario. Navegando antes, el ingreso
      // vería la sesión vieja, volvería a «/» y de ahí, ya sin sesión, al sitio.
      notifyManager.schedule(() => {
        void navigate('/ingresar', { replace: true })
      })
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
      {personal && item.staffLabel ? item.staffLabel : item.label}
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
                <span className="text-xs text-ink-muted">Mi cuenta</span>
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
            className="mx-auto hidden max-w-5xl flex-wrap gap-1 px-4 pb-2 sm:flex sm:px-6"
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
              Mi cuenta
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
        {sugerir2fa && (
          <div className="mb-8">
            <Alert
              tone="info"
              title="Te recomendamos activar la verificación en dos pasos"
              action={
                <div className="flex flex-wrap gap-3">
                  <Link
                    to="/cuenta/seguridad"
                    className="inline-flex min-h-11 items-center rounded-control border border-line-strong bg-surface px-4 text-sm font-semibold text-brand-800 no-underline hover:border-brand-700 hover:bg-brand-50"
                  >
                    Activarla ahora
                  </Link>
                  <button
                    type="button"
                    onClick={() => {
                      omitirMfaSugerido(user)
                      setOmitido(true)
                    }}
                    className="inline-flex min-h-11 cursor-pointer items-center rounded-control px-4 text-sm font-semibold text-brand-800 hover:bg-brand-50"
                  >
                    Ahora no
                  </button>
                </div>
              }
            >
              Tu rol tiene acceso a información sensible de la Caja: con este paso, aunque alguien
              conozca tu contraseña no puede entrar sin tu teléfono.
            </Alert>
          </div>
        )}
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
          {/* Ingreso y recuperación de clave: el logo y el enlace vuelven al sitio de la Caja. */}
          <BrandLogo to="/sitio" />
          <Link
            to="/sitio"
            className="inline-flex min-h-11 items-center gap-1.5 rounded-control px-3 text-sm font-medium no-underline hover:bg-brand-50"
          >
            <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
            Volver al sitio
          </Link>
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
