import { NavLink, Outlet } from 'react-router'

import { BrandLogo } from '../../components/BrandLogo'

function link({ isActive }: { isActive: boolean }): string {
  return `inline-flex min-h-11 items-center rounded-control px-3 text-sm font-medium no-underline transition-colors duration-150 ease-out-quint ${
    isActive
      ? 'bg-brand-50 text-brand-900'
      : 'text-ink-muted hover:bg-brand-50 hover:text-brand-800'
  }`
}

/** Sitio institucional público: sin sesión, con acceso a la Suite y a la verificación. */
export function SitioShell() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <BrandLogo to="/sitio" />
          <nav aria-label="Sitio institucional" className="-mx-3 flex flex-wrap gap-1">
            <NavLink to="/sitio" end className={link}>
              Inicio
            </NavLink>
            <NavLink to="/sitio/novedades" className={link}>
              Novedades
            </NavLink>
            <NavLink to="/verificar" className={link}>
              Verificar boleta
            </NavLink>
            <NavLink to="/ingresar" className={link}>
              Ingresar
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-10 sm:px-6 sm:py-14">
        <Outlet />
      </main>
      <footer className="border-t border-line bg-surface">
        <div className="mx-auto max-w-5xl px-4 py-6 text-sm text-ink-muted sm:px-6">
          Caja Notarial de San Juan · Los documentos se publican con su huella SHA-256: el archivo
          que descargás es idéntico al aprobado.
        </div>
      </footer>
    </div>
  )
}
