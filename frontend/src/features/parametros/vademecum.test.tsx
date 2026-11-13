import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as ddjjApi from '../ddjj/api'
import { buscarEnVademecum, normalizar } from '../ddjj/vademecum'
import { VademecumPage } from './VademecumPage'

vi.mock('../ddjj/api')

const ADMIN = {
  ...ESCRIBANO,
  email: 'admin@suite-notarial.example',
  roles: ['ROLE_ADMIN'],
  permissions: ['parameters:read', 'parameters:write', 'parameters:approve'],
  mfa_enabled: true,
  mfa_required: true,
  mfa_verified: true,
}
const LECTOR = { ...ADMIN, permissions: ['parameters:read'] }

const BASE = {
  version: 1,
  motivo_exencion: null,
  aclaracion: null,
  sinonimos: null,
  fecha_desde: '2026-06-01',
  fecha_hasta: null,
  resolucion: 'Vademécum de aportes · Asamblea Extraordinaria del 19/05/2026',
  estado: 'VIGENTE',
  created_by_user_id: 'u-autor',
  aprobado_por_user_id: 'u-revisor',
  created_at: '2026-06-01T12:00:00Z',
} as const

const ACTOS: ddjjApi.VademecumActo[] = [
  {
    ...BASE,
    id: 'v1',
    codigo: 'VENTA',
    nombre: 'Venta',
    categoria: 'ESCRITURA_CON_VALOR',
    sinonimos: 'compraventa',
    orden: 101,
  },
  {
    ...BASE,
    id: 'v2',
    codigo: 'TESTAMENTO',
    nombre: 'Testamento',
    categoria: 'OTRO_ACTO',
    orden: 216,
  },
  {
    ...BASE,
    id: 'v3',
    codigo: 'REGULACION_DOMINIAL',
    nombre: 'Acta de regulación dominial',
    categoria: 'EXENTO',
    motivo_exencion: 'REGULACION_DOMINIAL',
    orden: 404,
  },
]

const TESTAMENTO = ACTOS.find((a) => a.codigo === 'TESTAMENTO') as ddjjApi.VademecumActo

function renderPagina(user = ADMIN) {
  return renderWithProviders(
    <Routes>
      <Route path="/parametros/vademecum" element={<VademecumPage />} />
    </Routes>,
    { path: '/parametros/vademecum', user, raw: true },
  )
}

describe('búsqueda en el vademécum', () => {
  it('ignora tildes y mayúsculas y busca también en los sinónimos', () => {
    expect(normalizar('  Cesión ONEROSA ')).toBe('cesion onerosa')
    expect(buscarEnVademecum(ACTOS, 'compraventa').map((a) => a.codigo)).toEqual(['VENTA'])
    expect(buscarEnVademecum(ACTOS, 'regulacion acta').map((a) => a.codigo)).toEqual([
      'REGULACION_DOMINIAL',
    ])
    expect(buscarEnVademecum(ACTOS, '')).toHaveLength(3)
  })
})

describe('administración del vademécum', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(ddjjApi.fetchVademecum).mockResolvedValue(ACTOS)
    vi.mocked(ddjjApi.fetchVademecumPendientes).mockResolvedValue([])
  })

  it('lista los actos por categoría, en el orden del documento', async () => {
    renderPagina()
    expect(await screen.findByText('I · Aporte variable')).toBeInTheDocument()
    expect(screen.getByText('II · Aportes fijos mayores')).toBeInTheDocument()
    expect(screen.getByText('IV · Actos exentos o que no generan aporte')).toBeInTheDocument()
    expect(screen.queryByText('III · Aportes fijos menores')).not.toBeInTheDocument()
    expect(screen.getByText(BASE.resolucion)).toBeInTheDocument()
  })

  it('un cambio es una versión nueva con fecha, resolución y motivo', async () => {
    vi.mocked(ddjjApi.proponerVademecum).mockResolvedValue({ ...TESTAMENTO, version: 2 })
    renderPagina()
    fireEvent.click(await screen.findByRole('button', { name: 'Cambiar Testamento' }))
    const dialogo = await screen.findByRole('dialog')
    const guardar = within(dialogo).getByRole('button', { name: 'Proponer versión nueva' })
    expect(guardar).toBeDisabled()

    fireEvent.change(within(dialogo).getByLabelText('Cómo aporta'), {
      target: { value: 'ACTA_O_PODER' },
    })
    fireEvent.change(within(dialogo).getByLabelText('Rige desde'), {
      target: { value: '2027-01-01' },
    })
    fireEvent.change(within(dialogo).getByLabelText('Resolución o asamblea'), {
      target: { value: 'Asamblea 2027' },
    })
    fireEvent.change(within(dialogo).getByLabelText('Motivo'), {
      target: { value: 'Cambio de política' },
    })
    fireEvent.click(guardar)
    await waitFor(() => {
      expect(ddjjApi.proponerVademecum).toHaveBeenCalledWith(
        expect.objectContaining({
          codigo: 'TESTAMENTO',
          categoria: 'ACTA_O_PODER',
          fecha_desde: '2027-01-01',
          resolucion: 'Asamblea 2027',
          motivo: 'Cambio de política',
          orden: 216,
        }),
      )
    })
  })

  it('las propuestas las aprueba otra persona', async () => {
    const ajena = { ...TESTAMENTO, id: 'p1', version: 2, estado: 'PENDIENTE_APROBACION' as const }
    const propia = {
      ...ajena,
      id: 'p2',
      codigo: 'VENTA',
      nombre: 'Venta nueva',
      created_by_user_id: ADMIN.id,
    }
    vi.mocked(ddjjApi.fetchVademecumPendientes).mockResolvedValue([ajena, propia])
    vi.mocked(ddjjApi.aprobarVademecum).mockResolvedValue([])
    renderPagina()

    expect(await screen.findByText('Propuestas pendientes de aprobación')).toBeInTheDocument()
    expect(screen.getByText('La aprueba otra persona')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Aprobar Venta nueva' })).not.toBeInTheDocument()
    // Con una sola aprobable no se ofrece aprobar todas.
    expect(screen.queryByRole('button', { name: /Aprobar las/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Aprobar Testamento' }))
    await waitFor(() => {
      expect(ddjjApi.aprobarVademecum).toHaveBeenCalledWith(['p1'], expect.anything())
    })
  })

  it('sin permiso de escritura solo consulta', async () => {
    renderPagina(LECTOR)
    expect(await screen.findByText('Testamento')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Proponer acto' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cambiar/ })).not.toBeInTheDocument()
  })
})
