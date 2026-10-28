import { useQuery } from '@tanstack/react-query'
import { ChevronDown, LogIn, Mail, MapPin, Menu, Phone, X } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'

import { BrandLogo } from '../../components/BrandLogo'
import { fetchSitio, type Contacto } from '../cms/api'
import { grupos, type GrupoMenu } from './menu'

const hoy = new Intl.DateTimeFormat('es-AR', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'America/Argentina/San_Juan',
})

function telHref(telefono: string): string {
  return `tel:${telefono.replace(/[^\d+]/g, '')}`
}

function itemNav({ isActive }: { isActive: boolean }): string {
  return `inline-flex min-h-11 items-center rounded-control px-3 text-sm font-medium no-underline transition-colors duration-150 ease-out-quint ${
    isActive ? 'bg-brand-50 text-brand-900' : 'text-ink hover:bg-brand-50 hover:text-brand-800'
  }`
}

/** Menú desplegable de escritorio: se abre con clic o teclado y se cierra con Escape, al
 * hacer clic afuera o al navegar. */
function Desplegable({ grupo }: { grupo: GrupoMenu }) {
  const [abierto, setAbierto] = useState(false)
  const raiz = useRef<HTMLLIElement>(null)
  const boton = useRef<HTMLButtonElement>(null)
  const id = useId()
  const { pathname } = useLocation()
  const activo = grupo.enlaces.some((e) => e.to.split('?')[0] === pathname)

  useEffect(() => {
    if (!abierto) return
    function fuera(e: PointerEvent) {
      if (!raiz.current?.contains(e.target as Node)) setAbierto(false)
    }
    function tecla(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setAbierto(false)
        boton.current?.focus()
      }
    }
    document.addEventListener('pointerdown', fuera)
    document.addEventListener('keydown', tecla)
    return () => {
      document.removeEventListener('pointerdown', fuera)
      document.removeEventListener('keydown', tecla)
    }
  }, [abierto])

  return (
    <li ref={raiz} className="relative">
      <button
        ref={boton}
        type="button"
        aria-expanded={abierto}
        aria-controls={id}
        onClick={() => {
          setAbierto((v) => !v)
        }}
        className={`inline-flex min-h-11 items-center gap-1 rounded-control px-3 text-sm font-medium transition-colors duration-150 ease-out-quint hover:bg-brand-50 hover:text-brand-800 ${
          activo || abierto ? 'bg-brand-50 text-brand-900' : 'text-ink'
        }`}
      >
        {grupo.label}
        <ChevronDown
          aria-hidden="true"
          className={`size-4 transition-transform duration-150 ${abierto ? 'rotate-180' : ''}`}
          strokeWidth={2.25}
        />
      </button>
      <ul
        id={id}
        hidden={!abierto}
        className="absolute top-full left-0 z-30 mt-1 grid w-72 gap-0.5 rounded-panel border border-line bg-surface p-1.5 shadow-panel"
      >
        {grupo.enlaces.map((e) => (
          <li key={`${e.to}-${e.label}`}>
            <Link
              to={e.to}
              onClick={() => {
                setAbierto(false)
              }}
              className="flex min-h-11 items-center rounded-control px-3 text-sm text-ink no-underline hover:bg-brand-50 hover:text-brand-800"
            >
              {e.label}
            </Link>
          </li>
        ))}
      </ul>
    </li>
  )
}

function MenuCelular({ menu, onClose }: { menu: GrupoMenu[]; onClose: () => void }) {
  return (
    <nav
      aria-label="Sitio institucional"
      className="max-h-[calc(100dvh-4.5rem)] overflow-y-auto overscroll-contain border-t border-line bg-surface lg:hidden"
    >
      <div className="mx-auto grid max-w-6xl gap-5 px-4 py-5 sm:px-6">
        <NavLink to="/sitio/novedades" className={itemNav} onClick={onClose}>
          Novedades
        </NavLink>
        {menu.map((g) => (
          <div key={g.label}>
            <h2 className="px-3 text-sm font-semibold text-ink-muted">{g.label}</h2>
            <ul className="mt-1 grid">
              {g.enlaces.map((e) => (
                <li key={`${e.to}-${e.label}`}>
                  <Link
                    to={e.to}
                    onClick={onClose}
                    className="flex min-h-11 items-center rounded-control px-3 text-ink no-underline hover:bg-brand-50"
                  >
                    {e.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
        <NavLink to="/sitio/contacto" className={itemNav} onClick={onClose}>
          Contacto
        </NavLink>
      </div>
    </nav>
  )
}

function Pie({ contacto, menu }: { contacto: Contacto | undefined; menu: GrupoMenu[] }) {
  return (
    <footer className="mt-16 border-t border-line bg-surface">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-12 sm:px-6 md:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div className="grid content-start gap-4">
          <BrandLogo to="/sitio" />
          {contacto && (
            <address className="grid gap-2 text-sm text-ink-muted not-italic">
              {contacto.domicilio && (
                <span className="flex gap-2">
                  <MapPin
                    aria-hidden="true"
                    className="mt-0.5 size-4 shrink-0"
                    strokeWidth={2.25}
                  />
                  {contacto.domicilio}
                </span>
              )}
              {contacto.telefono && (
                <a href={telHref(contacto.telefono)} className="flex gap-2 tabular-nums">
                  <Phone aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={2.25} />
                  {contacto.telefono}
                </a>
              )}
              {contacto.email && (
                <a href={`mailto:${contacto.email}`} className="flex gap-2 break-all">
                  <Mail aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={2.25} />
                  {contacto.email}
                </a>
              )}
            </address>
          )}
        </div>
        {menu.map((g) => (
          <nav key={g.label} aria-label={g.label}>
            <h2 className="text-sm font-semibold text-brand-900">{g.label}</h2>
            <ul className="mt-3 grid gap-2 text-sm">
              {g.enlaces.map((e) => (
                <li key={`${e.to}-${e.label}`}>
                  <Link
                    to={e.to}
                    className="text-ink-muted no-underline hover:text-brand-800 hover:underline"
                  >
                    {e.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <div className="border-t border-line bg-surface-sunken">
        <p className="mx-auto max-w-6xl px-4 py-4 text-xs text-ink-muted sm:px-6">
          © Caja Notarial de San Juan · Los documentos oficiales se publican con su huella SHA-256:
          el archivo que descargás es idéntico al aprobado.
        </p>
      </div>
    </footer>
  )
}

/** Sitio institucional público, con estructura de diario: franja de contacto, cabecera con el
 * menú de la Caja y acceso a la Suite, y pie con el mapa del sitio. */
export function SitioShell() {
  const { data } = useQuery({ queryKey: ['sitio'], queryFn: fetchSitio })
  const menu = grupos(data?.menu ?? [])
  const { pathname } = useLocation()
  // El menú del celular queda abierto solo en la página donde se abrió: al navegar se cierra.
  const [abiertoEn, setAbiertoEn] = useState<string | null>(null)
  const abierto = abiertoEn === pathname
  const setAbierto = (valor: boolean) => {
    setAbiertoEn(valor ? pathname : null)
  }
  const contacto = data?.contacto

  return (
    <div className="flex min-h-dvh flex-col">
      <div className="bg-brand-900 text-brand-50">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-1 px-4 py-2 text-xs sm:px-6">
          <p className="first-letter:uppercase">{hoy.format(new Date())}</p>
          {contacto && (contacto.telefono || contacto.email) && (
            <p className="flex flex-wrap gap-x-5 gap-y-1">
              {contacto.telefono && (
                <a
                  href={telHref(contacto.telefono)}
                  className="inline-flex items-center gap-1.5 text-brand-50 tabular-nums no-underline hover:underline"
                >
                  <Phone aria-hidden="true" className="size-3.5" strokeWidth={2.25} />
                  {contacto.telefono}
                </a>
              )}
              {contacto.email && (
                <a
                  href={`mailto:${contacto.email}`}
                  className="inline-flex items-center gap-1.5 text-brand-50 no-underline hover:underline"
                >
                  <Mail aria-hidden="true" className="size-3.5" strokeWidth={2.25} />
                  {contacto.email}
                </a>
              )}
            </p>
          )}
        </div>
      </div>
      <header className="sticky top-0 z-20 border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <BrandLogo to="/sitio" />
          <nav aria-label="Sitio institucional" className="hidden lg:block">
            <ul className="flex items-center gap-1">
              <li>
                <NavLink to="/sitio/novedades" className={itemNav}>
                  Novedades
                </NavLink>
              </li>
              {menu.map((g) => (
                <Desplegable key={g.label} grupo={g} />
              ))}
              <li>
                <NavLink to="/sitio/contacto" className={itemNav}>
                  Contacto
                </NavLink>
              </li>
            </ul>
          </nav>
          <div className="flex items-center gap-2">
            <Link
              to="/ingresar"
              className="inline-flex min-h-11 items-center gap-2 rounded-control bg-brand-800 px-4 text-sm font-semibold text-white no-underline transition-colors duration-150 ease-out-quint hover:bg-brand-700 active:bg-brand-900"
            >
              <LogIn aria-hidden="true" className="size-4" strokeWidth={2.25} />
              <span className="sm:hidden">Ingresar</span>
              <span className="hidden sm:inline">Acceso afiliados</span>
            </Link>
            <button
              type="button"
              aria-expanded={abierto}
              aria-label={abierto ? 'Cerrar el menú' : 'Abrir el menú'}
              onClick={() => {
                setAbierto(!abierto)
              }}
              className="inline-flex size-11 items-center justify-center rounded-control border border-line-strong text-brand-800 hover:bg-brand-50 lg:hidden"
            >
              {abierto ? (
                <X aria-hidden="true" className="size-5" strokeWidth={2.25} />
              ) : (
                <Menu aria-hidden="true" className="size-5" strokeWidth={2.25} />
              )}
            </button>
          </div>
        </div>
        {abierto && (
          <MenuCelular
            menu={menu}
            onClose={() => {
              setAbierto(false)
            }}
          />
        )}
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 pt-8 sm:px-6 sm:pt-10">
        <Outlet />
      </main>
      <Pie contacto={contacto} menu={menu} />
    </div>
  )
}
