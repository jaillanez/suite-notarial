import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router'

import { PageHeader, Panel } from '../../components/ui/Panel'
import { roleLabel } from '../auth/roles'
import { useSession } from '../auth/session'

interface Section {
  to: string
  title: string
  description: string
  permission?: string | string[]
}

const SECTIONS: Section[] = [
  {
    to: '/ddjj',
    title: 'Declaraciones juradas',
    description: 'Actos del mes por registro, liquidación de aportes y boletas de pago.',
    permission: ['ddjj:read_own', 'ddjj:read_all', 'ddjj:approve'],
  },
  {
    to: '/tesoreria/conciliacion',
    title: 'Conciliación de pagos',
    description: 'Comprobantes en revisión: confirmar el pago contra el extracto o rechazarlo.',
    permission: 'comprobantes:verify',
  },
  {
    to: '/padron/escribanos',
    title: 'Escribanos',
    description: 'Padrón de matriculados: datos, estado de la matrícula y cargos.',
    permission: 'escribanos:read',
  },
  {
    to: '/padron/registros',
    title: 'Registros notariales',
    description: 'Registros con su titular, adscriptos y circunscripción.',
    permission: 'escribanos:read',
  },
  {
    to: '/parametros',
    title: 'Parámetros previsionales',
    description: 'Alícuotas, montos fijos y tasas con sus vigencias y aprobaciones.',
    permission: 'parameters:read',
  },
  {
    to: '/reportes',
    title: 'Reportes',
    description: 'Padrón, boletas, pagos, recaudación y auditoría, exportables a Excel y CSV.',
    permission: ['reports:financial', 'audit:read', 'escribanos:read'],
  },
  {
    to: '/prestamos',
    title: 'Préstamos',
    description: 'Simulación, solicitudes, otorgamiento y cobro de cuotas.',
    permission: ['prestamos:read_own', 'prestamos:read_all', 'prestamos:manage'],
  },
  {
    to: '/cms',
    title: 'Sitio institucional',
    description: 'Novedades, autoridades y documentos oficiales del sitio público.',
    permission: 'cms:publish',
  },
  {
    to: '/usuarios',
    title: 'Usuarios',
    description: 'Altas, suspensiones y roles de las cuentas de la Suite.',
    permission: 'users:read',
  },
  {
    to: '/auditoria',
    title: 'Auditoría',
    description: 'Registro inmutable de ingresos, cambios de permisos y acciones sensibles.',
    permission: 'audit:read',
  },
  {
    to: '/cuenta/seguridad',
    title: 'Seguridad de la cuenta',
    description: 'Verificación en dos pasos y códigos de recuperación.',
  },
  {
    to: '/estado',
    title: 'Estado del sistema',
    description: 'Disponibilidad de la API y de la base de datos.',
  },
]

export function HomePage() {
  const { user, can } = useSession()
  if (!user) return null
  const firstName = user.full_name.split(' ')[0] ?? user.full_name
  const sections = SECTIONS.filter(
    (s) => !s.permission || [s.permission].flat().some((p) => can(p)),
  )

  return (
    <>
      <PageHeader
        title={`Hola, ${firstName}`}
        description={`Ingresaste como ${user.roles.map(roleLabel).join(', ') || 'usuario sin rol'}.`}
      />
      <Panel title="Secciones disponibles">
        <ul className="divide-y divide-line">
          {sections.map((section) => (
            <li key={section.to}>
              <Link
                to={section.to}
                className="group flex items-center justify-between gap-4 px-5 py-4 text-ink no-underline transition-colors duration-150 ease-out-quint hover:bg-brand-50 sm:px-6"
              >
                <span>
                  <span className="block font-semibold text-brand-800">{section.title}</span>
                  <span className="mt-0.5 block text-sm text-ink-muted">{section.description}</span>
                </span>
                <ChevronRight
                  aria-hidden="true"
                  className="size-5 shrink-0 text-ink-subtle group-hover:text-brand-800"
                  strokeWidth={2}
                />
              </Link>
            </li>
          ))}
        </ul>
      </Panel>
    </>
  )
}
