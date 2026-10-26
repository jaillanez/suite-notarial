import { ExternalLink } from 'lucide-react'
import { Link, NavLink, Outlet } from 'react-router'

import { PageHeader } from '../../components/ui/Panel'

function tab({ isActive }: { isActive: boolean }): string {
  return `inline-flex min-h-11 items-center border-b-2 px-3 text-sm font-medium no-underline transition-colors duration-150 ease-out-quint ${
    isActive
      ? 'border-brand-800 text-brand-900'
      : 'border-transparent text-ink-muted hover:border-line-strong hover:text-brand-800'
  }`
}

export function CmsLayout() {
  return (
    <>
      <PageHeader
        title="Sitio institucional"
        description={
          <>
            Lo publicado se ve sin iniciar sesión en el{' '}
            <Link to="/sitio" target="_blank" className="inline-flex items-center gap-1">
              sitio público
              <ExternalLink aria-hidden="true" className="size-3.5" strokeWidth={2.25} />
            </Link>
            . Cada alta, cambio y publicación queda en la auditoría.
          </>
        }
      />
      <nav aria-label="Secciones del sitio" className="mb-6 flex gap-2 border-b border-line">
        <NavLink to="/cms/novedades" className={tab}>
          Novedades
        </NavLink>
        <NavLink to="/cms/documentos" className={tab}>
          Documentos
        </NavLink>
        <NavLink to="/cms/autoridades" className={tab}>
          Autoridades
        </NavLink>
      </nav>
      <Outlet />
    </>
  )
}
