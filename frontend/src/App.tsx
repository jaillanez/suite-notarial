import { createBrowserRouter, Navigate, RouterProvider } from 'react-router'

import { AppShell, PublicShell } from './components/AppShell'
import { AuditPage } from './features/audit/AuditPage'
import { AccountSecurityPage } from './features/auth/AccountSecurityPage'
import { ForgotPasswordPage } from './features/auth/ForgotPasswordPage'
import { RedirectIfAuthenticated, RequireAuth, RequirePermission } from './features/auth/guards'
import { LoginPage } from './features/auth/LoginPage'
import { ResetPasswordPage } from './features/auth/ResetPasswordPage'
import { DeclaracionesPage } from './features/ddjj/DeclaracionesPage'
import { DeclaracionPage } from './features/ddjj/DeclaracionPage'
import { MinutaPage } from './features/ia/MinutaPage'
import { CorridaPage } from './features/migracion/CorridaPage'
import { CorridasPage } from './features/migracion/CorridasPage'
import { VerificarBoletaPage } from './features/ddjj/VerificarBoletaPage'
import { ComprobantePage } from './features/pagos/ComprobantePage'
import { ConciliacionPage } from './features/pagos/ConciliacionPage'
import { ReportePage } from './features/reportes/ReportePage'
import { ReportesPage } from './features/reportes/ReportesPage'
import { AutoridadesAdmin } from './features/cms/AutoridadesAdmin'
import { CmsLayout } from './features/cms/CmsLayout'
import { DocumentosAdmin } from './features/cms/DocumentosAdmin'
import { NovedadesAdmin } from './features/cms/NovedadesAdmin'
import { NovedadPublicaPage } from './features/sitio/NovedadPublicaPage'
import { NovedadesPublicasPage } from './features/sitio/NovedadesPublicasPage'
import { SitioPage } from './features/sitio/SitioPage'
import { SitioShell } from './features/sitio/SitioShell'
import { LineasPage } from './features/prestamos/LineasPage'
import { PrestamoPage } from './features/prestamos/PrestamoPage'
import { PrestamosPage } from './features/prestamos/PrestamosPage'
import { SimuladorPage } from './features/prestamos/SimuladorPage'
import { SolicitudPage } from './features/prestamos/SolicitudPage'
import { SystemStatusPage } from './features/health/SystemStatusPage'
import { HomePage } from './features/home/HomePage'
import { EscribanoNuevoPage } from './features/padron/EscribanoNuevoPage'
import { EscribanoPage } from './features/padron/EscribanoPage'
import { EscribanosPage } from './features/padron/EscribanosPage'
import { RegistroPage } from './features/padron/RegistroPage'
import { RegistrosPage } from './features/padron/RegistrosPage'
import { ConceptoPage } from './features/parametros/ConceptoPage'
import { ParametrosPage } from './features/parametros/ParametrosPage'
import { UsersPage } from './features/users/UsersPage'
import { ACargoPage } from './features/acargo/ACargoPage'
import { IndicePage } from './features/ia/IndicePage'
import { RetornoMercadoPagoPage } from './features/pagos/RetornoMercadoPagoPage'

const router = createBrowserRouter([
  {
    element: <RedirectIfAuthenticated />,
    children: [
      {
        element: <PublicShell />,
        children: [
          { path: '/ingresar', element: <LoginPage /> },
          { path: '/recuperar-clave', element: <ForgotPasswordPage /> },
        ],
      },
    ],
  },
  {
    // Accesible con o sin sesión: el enlace llega por correo.
    element: <PublicShell />,
    children: [
      { path: '/restablecer-clave', element: <ResetPasswordPage /> },
      // Verificación pública de boletas (QR impreso): no requiere sesión.
      { path: '/verificar', element: <VerificarBoletaPage /> },
      { path: '/verificar/:codigo', element: <VerificarBoletaPage /> },
    ],
  },
  {
    // Sitio institucional público: sin sesión.
    element: <SitioShell />,
    children: [
      { path: '/sitio', element: <SitioPage /> },
      { path: '/sitio/novedades', element: <NovedadesPublicasPage /> },
      { path: '/sitio/novedades/:slug', element: <NovedadPublicaPage /> },
    ],
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: '/', element: <HomePage /> },
          { path: '/cuenta/seguridad', element: <AccountSecurityPage /> },
          { path: '/estado', element: <SystemStatusPage /> },
          {
            element: <RequirePermission permission="users:read" />,
            children: [{ path: '/usuarios', element: <UsersPage /> }],
          },
          {
            element: <RequirePermission permission="escribanos:read" />,
            children: [
              { path: '/padron/escribanos', element: <EscribanosPage /> },
              { path: '/padron/escribanos/:id', element: <EscribanoPage /> },
              { path: '/padron/registros', element: <RegistrosPage /> },
              { path: '/padron/registros/:id', element: <RegistroPage /> },
            ],
          },
          {
            element: <RequirePermission permission="escribanos:write" />,
            children: [{ path: '/padron/escribanos/nuevo', element: <EscribanoNuevoPage /> }],
          },
          {
            element: <RequirePermission permission="parameters:read" />,
            children: [
              { path: '/parametros', element: <ParametrosPage /> },
              { path: '/parametros/:id', element: <ConceptoPage /> },
            ],
          },
          {
            element: (
              <RequirePermission permission={['ddjj:read_own', 'ddjj:read_all', 'ddjj:approve']} />
            ),
            children: [
              { path: '/ddjj', element: <DeclaracionesPage /> },
              { path: '/ddjj/:id', element: <DeclaracionPage /> },
              { path: '/ddjj/:id/minuta', element: <MinutaPage /> },
              { path: '/ddjj/:id/indice', element: <IndicePage /> },
              { path: '/pagos/mercadopago/retorno', element: <RetornoMercadoPagoPage /> },
            ],
          },
          {
            element: (
              <RequirePermission
                permission={['escribanos:read', 'ddjj:create_own', 'ddjj:read_own']}
              />
            ),
            children: [{ path: '/a-cargo', element: <ACargoPage /> }],
          },
          {
            element: <RequirePermission permission="comprobantes:verify" />,
            children: [
              { path: '/tesoreria/conciliacion', element: <ConciliacionPage /> },
              { path: '/tesoreria/conciliacion/:id', element: <ComprobantePage /> },
            ],
          },
          {
            element: (
              <RequirePermission
                permission={['reports:financial', 'audit:read', 'escribanos:read']}
              />
            ),
            children: [
              { path: '/reportes', element: <ReportesPage /> },
              { path: '/reportes/:codigo', element: <ReportePage /> },
            ],
          },
          {
            element: (
              <RequirePermission
                permission={['prestamos:read_own', 'prestamos:read_all', 'prestamos:manage']}
              />
            ),
            children: [
              { path: '/prestamos', element: <PrestamosPage /> },
              { path: '/prestamos/simular', element: <SimuladorPage /> },
              { path: '/prestamos/:id', element: <PrestamoPage /> },
            ],
          },
          {
            element: <RequirePermission permission="prestamos:manage" />,
            children: [
              { path: '/prestamos/nueva', element: <SolicitudPage /> },
              { path: '/prestamos/lineas', element: <LineasPage /> },
            ],
          },
          {
            element: <RequirePermission permission="migracion:read" />,
            children: [
              { path: '/migracion', element: <CorridasPage /> },
              { path: '/migracion/:id', element: <CorridaPage /> },
            ],
          },
          {
            element: <RequirePermission permission="cms:publish" />,
            children: [
              {
                path: '/cms',
                element: <CmsLayout />,
                children: [
                  { index: true, element: <Navigate to="/cms/novedades" replace /> },
                  { path: 'novedades', element: <NovedadesAdmin /> },
                  { path: 'documentos', element: <DocumentosAdmin /> },
                  { path: 'autoridades', element: <AutoridadesAdmin /> },
                ],
              },
            ],
          },
          {
            element: <RequirePermission permission="audit:read" />,
            children: [{ path: '/auditoria', element: <AuditPage /> }],
          },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])

export function App() {
  return <RouterProvider router={router} />
}
