import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as padronApi from './api'
import { EscribanoNuevoPage } from './EscribanoNuevoPage'
import { EscribanoPage } from './EscribanoPage'
import { EscribanosPage } from './EscribanosPage'
import { aniosMeses, formatDate } from './labels'
import { RegistroPage } from './RegistroPage'

vi.mock('./api')

const CAJA = {
  ...ESCRIBANO,
  roles: ['ROLE_CAJA'],
  permissions: ['escribanos:read', 'escribanos:write', 'escribanos:status'],
}

describe('padrón', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(padronApi.fetchDepartamentos).mockResolvedValue(['Capital', 'Rivadavia'])
  })

  it('formatea fechas calendario sin corrimiento de zona', () => {
    expect(formatDate('2015-03-01')).toBe('01/03/2015')
    expect(formatDate(null)).toBe('—')
  })

  it('lista escribanos y filtra en el servidor', async () => {
    vi.mocked(padronApi.fetchEscribanos).mockResolvedValue({
      items: [
        {
          id: 'e1',
          matricula_numero: 101,
          tomo: null,
          folio: null,
          fecha_matriculacion: '2015-03-01',
          estado_matricula: 'SUSPENDIDO',
          apellido_nombre: 'Quiroga, Facundo',
          cuit: '20-00001400-2',
          numero_documento: '00001400',
          registro_actual: 2,
          cargo_actual: 'TITULAR',
          tiene_cuenta: false,
          en_licencia_desde: '2026-10-01',
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
    })
    renderWithProviders(<EscribanosPage />, { path: '/padron/escribanos', user: CAJA })

    expect((await screen.findAllByText('Quiroga, Facundo')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Suspendido').length).toBeGreaterThan(0)
    expect(screen.getAllByText('En licencia').length).toBeGreaterThan(0)

    fireEvent.change(screen.getByLabelText('Estado'), { target: { value: 'CESANTE' } })
    await waitFor(() => {
      expect(padronApi.fetchEscribanos).toHaveBeenLastCalledWith(
        expect.objectContaining({ estado: 'CESANTE', page: 1 }),
      )
    })
  })

  it('da de alta un escribano con persona y matrícula', async () => {
    vi.mocked(padronApi.createEscribano).mockResolvedValue({
      id: 'nuevo',
    } as padronApi.EscribanoDetalle)
    renderWithProviders(<EscribanoNuevoPage />, {
      path: '/padron/escribanos/nuevo',
      user: CAJA,
    })

    const type = (label: string, value: string) => {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
    type('Apellido', 'Sarmiento')
    type('Nombre', 'Domingo')
    type('CUIT', '20-30111222-0')
    type('Número', '30111222')
    type('Número de matrícula', '450')
    type('Fecha de juramento', '2020-05-15')
    const submit = screen.getByRole('button', { name: 'Dar de alta' })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)
    await waitFor(() => {
      expect(padronApi.createEscribano).toHaveBeenCalled()
    })

    expect(padronApi.createEscribano).toHaveBeenCalledWith(
      expect.objectContaining({
        matricula_numero: 450,
        fecha_matriculacion: '2020-05-15',
        persona: expect.objectContaining({ apellido: 'Sarmiento', email: null }) as unknown,
      }),
    )
  })

  it('muestra los datos a completar y los carga una vez', async () => {
    const migrado: padronApi.EscribanoDetalle = {
      id: 'e9',
      matricula_numero: null,
      tomo: null,
      folio: null,
      fecha_matriculacion: null,
      estado_matricula: 'ACTIVO',
      apellido_nombre: 'Sintético, Histórico',
      cuit: null,
      numero_documento: null,
      registro_actual: null,
      cargo_actual: null,
      tiene_cuenta: false,
      en_licencia_desde: null,
      persona: {
        id: 'p9',
        cuit: null,
        tipo_documento: 'DNI',
        numero_documento: null,
        apellido: 'Sintético',
        nombre: 'Histórico',
        fecha_nacimiento: null,
        email: 'historico@ejemplo.test',
        telefono: null,
        domicilio_real: null,
      },
      transiciones_permitidas: [],
      transiciones_con_resolucion: [],
      motivo_ultimo_cambio_estado: null,
      fecha_ultimo_cambio_estado: null,
      a_completar: [
        'matricula_numero',
        'fecha_matriculacion',
        'cuit',
        'numero_documento',
        'primera_escritura',
      ],
      cargos: [],
      historial: [],
      primera_escritura: null,
      antiguedad: null,
      licencias: [],
      designaciones_a_cargo: [],
    }
    vi.mocked(padronApi.fetchEscribano).mockResolvedValue(migrado)
    vi.mocked(padronApi.completarEscribano).mockResolvedValue({
      ...migrado,
      matricula_numero: 512,
      a_completar: ['fecha_matriculacion', 'cuit', 'numero_documento', 'primera_escritura'],
    })
    renderWithProviders(
      <Routes>
        <Route path="/padron/escribanos/:id" element={<EscribanoPage />} />
      </Routes>,
      {
        path: '/padron/escribanos/e9',
        user: { ...CAJA, permissions: [...CAJA.permissions, 'users:write'] },
        raw: true,
      },
    )

    expect(await screen.findByText('Matrícula a completar')).toBeInTheDocument()
    expect(screen.getByText('CUIT a completar')).toBeInTheDocument()
    // Matrícula, juramento, CUIT, DNI, primera escritura y antigüedad.
    expect(screen.getAllByText('A completar')).toHaveLength(6)
    // Sin CUIT no se puede crear la cuenta de autogestión.
    expect(screen.getByRole('button', { name: 'Crear cuenta de autogestión' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Completar datos' }))
    const guardar = screen.getByRole('button', { name: 'Guardar datos' })
    expect(guardar).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Matrícula'), { target: { value: '512' } })
    fireEvent.click(guardar)
    await waitFor(() => {
      expect(padronApi.completarEscribano).toHaveBeenCalledWith('e9', { matricula_numero: 512 })
    })
  })

  const FICHA: padronApi.EscribanoDetalle = {
    id: 'e5',
    matricula_numero: 77,
    tomo: null,
    folio: null,
    fecha_matriculacion: '2010-03-01',
    estado_matricula: 'ACTIVO',
    apellido_nombre: 'Prueba, Licencia',
    cuit: '20-30111222-0',
    numero_documento: '30111222',
    registro_actual: 12,
    cargo_actual: 'TITULAR',
    tiene_cuenta: false,
    en_licencia_desde: '2026-09-01',
    persona: {
      id: 'p5',
      cuit: '20-30111222-0',
      tipo_documento: 'DNI',
      numero_documento: '30111222',
      apellido: 'Prueba',
      nombre: 'Licencia',
      fecha_nacimiento: null,
      email: null,
      telefono: null,
      domicilio_real: null,
    },
    transiciones_permitidas: ['SUSPENDIDO'],
    transiciones_con_resolucion: [],
    motivo_ultimo_cambio_estado: null,
    fecha_ultimo_cambio_estado: null,
    a_completar: [],
    cargos: [
      {
        id: 'c2',
        registro_id: 'r12',
        numero_registro: 12,
        cargo: 'TITULAR',
        resolucion_designacion: null,
        fecha_desde: '2015-01-01',
        fecha_hasta: null,
        motivo_cierre: null,
        is_current: true,
      },
      {
        id: 'c1',
        registro_id: 'r3',
        numero_registro: 3,
        cargo: 'ADSCRIPTO',
        resolucion_designacion: null,
        fecha_desde: '2010-05-01',
        fecha_hasta: '2014-12-31',
        motivo_cierre: 'Pasa a titular',
        is_current: false,
      },
    ],
    historial: [],
    primera_escritura: {
      fecha: '2010-06-15',
      numero: '1',
      registro: 3,
      folio: '12',
      cargada_por: 'caja@ejemplo.test',
      cargada_en: '2026-11-01T12:00:00Z',
    },
    antiguedad: { desde: '2010-06-15', anios: 16, meses: 4 },
    licencias: [
      {
        id: 'l1',
        fecha_desde: '2026-09-01',
        fecha_hasta: null,
        motivo: 'Licencia por estudios',
        resolucion_respaldo: null,
        anulada: false,
        motivo_anulacion: null,
        anulada_en: null,
        vigente: true,
        cargada_por: 'caja@ejemplo.test',
        created_at: '2026-09-01T12:00:00Z',
      },
    ],
    designaciones_a_cargo: [],
  }

  function renderFicha() {
    renderWithProviders(
      <Routes>
        <Route path="/padron/escribanos/:id" element={<EscribanoPage />} />
      </Routes>,
      { path: '/padron/escribanos/e5', user: CAJA, raw: true },
    )
  }

  it('muestra licencia vigente, antigüedad e historia completa de cargos', async () => {
    vi.mocked(padronApi.fetchEscribano).mockResolvedValue(FICHA)
    vi.mocked(padronApi.terminarLicencia).mockResolvedValue({
      ...FICHA,
      en_licencia_desde: null,
    })
    renderFicha()

    expect(await screen.findByText('En licencia desde el 01/09/2026')).toBeInTheDocument()
    expect(screen.getByText('Fecha de juramento')).toBeInTheDocument()
    expect(screen.getByText(aniosMeses(16, 4))).toBeInTheDocument()
    expect(aniosMeses(1, 1)).toBe('1 año 1 mes')
    expect(screen.getByText('Titular · Registro 12')).toBeInTheDocument()
    expect(screen.getByText('Adscripto · Registro 3')).toBeInTheDocument()
    // Con una licencia vigente no se registra otra.
    expect(screen.queryByRole('button', { name: 'Registrar licencia' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Terminar' }))
    fireEvent.change(screen.getByLabelText('Último día de licencia'), {
      target: { value: '2026-10-31' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Terminar licencia' }))
    await waitFor(() => {
      expect(padronApi.terminarLicencia).toHaveBeenCalledWith('l1', '2026-10-31')
    })
  })

  it('registra una licencia y corrige la primera escritura con motivo', async () => {
    const sinLicencia = { ...FICHA, en_licencia_desde: null, licencias: [] }
    vi.mocked(padronApi.fetchEscribano).mockResolvedValue(sinLicencia)
    vi.mocked(padronApi.iniciarLicencia).mockResolvedValue(FICHA)
    vi.mocked(padronApi.guardarPrimeraEscritura).mockResolvedValue(sinLicencia)
    renderFicha()

    fireEvent.click(await screen.findByRole('button', { name: 'Registrar licencia' }))
    const licencia = within(screen.getByRole('dialog', { name: 'Registrar licencia' }))
    fireEvent.change(licencia.getByLabelText('Desde'), { target: { value: '2026-11-01' } })
    fireEvent.change(licencia.getByLabelText('Motivo'), { target: { value: 'Viaje al exterior' } })
    fireEvent.click(licencia.getByRole('button', { name: 'Registrar licencia' }))
    await waitFor(() => {
      expect(padronApi.iniciarLicencia).toHaveBeenCalledWith('e5', {
        fecha_desde: '2026-11-01',
        fecha_hasta: null,
        motivo: 'Viaje al exterior',
        resolucion_respaldo: null,
      })
    })

    fireEvent.click(screen.getByRole('button', { name: 'Corregir' }))
    const correccion = within(screen.getByRole('dialog', { name: 'Corregir primera escritura' }))
    const guardar = correccion.getByRole('button', { name: 'Guardar corrección' })
    expect(guardar).toBeDisabled() // sin motivo
    fireEvent.change(correccion.getByLabelText('Número de escritura'), { target: { value: '2' } })
    fireEvent.change(correccion.getByLabelText('Motivo de la corrección'), {
      target: { value: 'Error de tipeo' },
    })
    fireEvent.click(guardar)
    await waitFor(() => {
      expect(padronApi.guardarPrimeraEscritura).toHaveBeenCalledWith('e5', {
        fecha: '2010-06-15',
        numero: '2',
        registro: 3,
        folio: '12',
        motivo: 'Error de tipeo',
      })
    })
  })

  it('carga la primera escritura desde «Completar datos» solo completa', async () => {
    const sinPrimera = {
      ...FICHA,
      a_completar: ['primera_escritura'] as padronApi.CampoACompletar[],
      primera_escritura: null,
      antiguedad: null,
    }
    vi.mocked(padronApi.fetchEscribano).mockResolvedValue(sinPrimera)
    vi.mocked(padronApi.completarEscribano).mockResolvedValue(FICHA)
    renderFicha()

    fireEvent.click(await screen.findByRole('button', { name: 'Completar datos' }))
    const completar = within(screen.getByRole('dialog', { name: 'Completar datos' }))
    const guardar = completar.getByRole('button', { name: 'Guardar datos' })
    fireEvent.change(completar.getByLabelText('Fecha de la primera escritura'), {
      target: { value: '2010-06-15' },
    })
    expect(guardar).toBeDisabled() // falta número y registro
    fireEvent.change(completar.getByLabelText('Número de escritura'), { target: { value: '1' } })
    fireEvent.change(completar.getByLabelText(/^Registro/), { target: { value: '3' } })
    fireEvent.click(guardar)
    await waitFor(() => {
      expect(padronApi.completarEscribano).toHaveBeenCalledWith('e5', {
        primera_escritura: { fecha: '2010-06-15', numero: '1', registro: 3, folio: null },
      })
    })
  })

  it('muestra la historia del domicilio y lo cambia con fecha', async () => {
    const registro: padronApi.RegistroDetalle = {
      id: 'r12',
      numero_registro: 12,
      nombre_fantasia: null,
      circunscripcion: { id: 'c', nombre: 'San Juan', descripcion: null, is_active: true },
      departamento: 'Capital',
      domicilio_legal: 'Av. Libertador 450',
      telefono: null,
      email: null,
      fecha_creacion: '2001-05-02',
      estado: 'ACTIVO',
      titular: null,
      cantidad_adscriptos: 0,
      cargos_vigentes: [],
      domicilios: [
        {
          id: 'd2',
          domicilio: 'Av. Libertador 450',
          fecha_desde: '2020-03-01',
          fecha_hasta: null,
          cargado_por: null,
          created_at: '2020-03-01T12:00:00Z',
        },
        {
          id: 'd1',
          domicilio: 'Calle Vieja 123',
          fecha_desde: '2001-05-02',
          fecha_hasta: '2020-02-29',
          cargado_por: null,
          created_at: '2001-05-02T12:00:00Z',
        },
      ],
    }
    vi.mocked(padronApi.fetchRegistro).mockResolvedValue(registro)
    vi.mocked(padronApi.cambiarDomicilio).mockResolvedValue(registro)
    renderWithProviders(
      <Routes>
        <Route path="/padron/registros/:id" element={<RegistroPage />} />
      </Routes>,
      { path: '/padron/registros/r12', user: CAJA, raw: true },
    )

    expect(await screen.findByText('Calle Vieja 123')).toBeInTheDocument()
    expect(screen.getByText('01/03/2020 — vigente')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cambiar domicilio' }))
    fireEvent.change(screen.getByLabelText('Nuevo domicilio legal'), {
      target: { value: 'Mitre 10' },
    })
    fireEvent.change(screen.getByLabelText('Rige desde'), { target: { value: '2026-11-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Guardar domicilio' }))
    await waitFor(() => {
      expect(padronApi.cambiarDomicilio).toHaveBeenCalledWith('r12', 'Mitre 10', '2026-11-01')
    })
  })
})
