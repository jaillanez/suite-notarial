import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as apiModule from '../cms/api'
import { NovedadesAdmin } from '../cms/NovedadesAdmin'
import { parrafos, rutaLocal } from '../cms/labels'
import { PortadaAdmin } from '../cms/PortadaAdmin'
import { DocumentosPublicosPage } from './InstitucionalPages'
import { NovedadPublicaPage } from './NovedadPublicaPage'
import { SitioPage } from './SitioPage'

vi.mock('../cms/api')

const DOC: apiModule.DocumentoPublico = {
  slug: 'estados-contables-2025',
  tipo: 'ESTADO_CONTABLE',
  tipo_texto: 'Estados contables',
  ejercicio: 2025,
  titulo: 'Estados contables al 31 de diciembre',
  descripcion: null,
  fecha_publicacion: '2026-03-01T12:00:00Z',
  url: 'https://suite.cajanotarial-sj.test/api/v1/publico/documentos/estados-contables-2025.pdf',
  paginas: 13,
  tamano_bytes: 2048,
  sha256: 'a'.repeat(64),
  version: 2,
  actualizado: '2026-04-01T12:00:00Z',
  motivo_actualizacion: 'Se corrigió la nota 4.',
  versiones_anteriores: [
    {
      version: 1,
      sha256: 'b'.repeat(64),
      tamano_bytes: 2000,
      paginas: 12,
      motivo: null,
      created_at: '2026-03-01T12:00:00Z',
      url: 'https://suite.cajanotarial-sj.test/api/v1/publico/documentos/estados-contables-2025/v1.pdf',
    },
  ],
}

function nota(
  slug: string,
  extra: Partial<apiModule.NovedadResumen> = {},
): apiModule.NovedadResumen {
  return {
    slug,
    titulo: `Nota ${slug}`,
    resumen: null,
    seccion: 'NOVEDADES',
    seccion_texto: 'Novedades',
    fecha_publicacion: '2026-10-01T12:00:00Z',
    imagen_url: null,
    imagen_alt: null,
    ...extra,
  }
}

const AUTORIDAD: apiModule.Autoridad = {
  id: 'a1',
  cargo: 'Presidente',
  nombre: 'Esc. Demo',
  orden: 1,
  mandato_desde: null,
  mandato_hasta: null,
  is_active: true,
}

function sitio(extra: Partial<apiModule.Sitio> = {}): apiModule.Sitio {
  return {
    portada: { destacadas: [], filas: [] },
    menu: [],
    contacto: { nombre: 'Caja Notarial de San Juan', domicilio: null, telefono: null, email: null },
    autoridades: [AUTORIDAD],
    novedades: [],
    documentos: [DOC],
    ...extra,
  }
}

describe('utilidades del sitio', () => {
  it('separa párrafos y usa rutas locales para los enlaces', () => {
    expect(parrafos('Uno.\n\nDos\ncon salto.\n\n\n')).toEqual(['Uno.', 'Dos\ncon salto.'])
    expect(rutaLocal(DOC.url)).toBe('/api/v1/publico/documentos/estados-contables-2025.pdf')
  })
})

describe('sitio público', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('arma la portada: destacadas con flechas, servicios, filas y autoridades', async () => {
    vi.mocked(apiModule.fetchSitio).mockResolvedValue(
      sitio({
        portada: {
          destacadas: [
            nota('uno', { titulo: 'Aporte médico', seccion: 'APORTES', seccion_texto: 'Aportes' }),
            nota('dos', { titulo: 'Nuevas autoridades' }),
          ],
          filas: [{ distribucion: '2+1+1', notas: [nota('tres'), nota('cuatro')] }],
        },
      }),
    )

    renderWithProviders(<SitioPage />, { path: '/sitio' })

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Aporte médico' }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Nota destacada siguiente' }))
    expect(
      screen.getByRole('heading', { level: 1, name: 'Nuevas autoridades' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Generar declaración jurada/ })).toHaveAttribute(
      'href',
      '/ddjj',
    )
    expect(screen.getByRole('heading', { name: 'Nota tres' })).toBeInTheDocument()
    expect(screen.getByText('Presidente')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /Descargar Estados contables al 31 de diciembre 2025/ }),
    ).toHaveAttribute('href', '/api/v1/publico/documentos/estados-contables-2025.pdf')
  })

  it('muestra documentos con descarga, versión vigente, motivo e historial', async () => {
    vi.mocked(apiModule.fetchSitio).mockResolvedValue(sitio())

    renderWithProviders(<DocumentosPublicosPage />, { path: '/sitio/documentos' })

    expect(await screen.findByText('Estados contables al 31 de diciembre')).toBeInTheDocument()
    expect(screen.getByText('Motivo: Se corrigió la nota 4.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Descargar PDF/ })).toHaveAttribute(
      'href',
      '/api/v1/publico/documentos/estados-contables-2025.pdf',
    )
    expect(screen.getByRole('link', { name: 'Versión 1' })).toBeInTheDocument()
  })

  it('el contenido de una novedad se muestra como texto, nunca como HTML', async () => {
    vi.mocked(apiModule.fetchNovedadPublica).mockResolvedValue({
      ...nota('n', { titulo: 'Novedad' }),
      contenido: 'Primero.\n\n<img src=x onerror=alert(1)>',
    })

    const { container } = renderWithProviders(
      <Routes>
        <Route path="/sitio/novedades/:slug" element={<NovedadPublicaPage />} />
      </Routes>,
      { path: '/sitio/novedades/n', raw: true },
    )

    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
  })
})

describe('administración de novedades', () => {
  it('publica un borrador', async () => {
    vi.resetAllMocks()
    const borrador: apiModule.Novedad = {
      id: 'n1',
      slug: 'aviso',
      titulo: 'Aviso',
      resumen: null,
      contenido: 'Contenido del aviso.',
      seccion: 'COMUNICADOS',
      estado: 'BORRADOR',
      fecha_publicacion: null,
      imagen_url: null,
      imagen_alt: null,
      autor: null,
      created_at: '2026-10-25T12:00:00Z',
      updated_at: '2026-10-25T12:00:00Z',
    }
    vi.mocked(apiModule.fetchNovedades).mockResolvedValue({
      items: [borrador],
      total: 1,
      page: 1,
      page_size: 20,
    })
    vi.mocked(apiModule.estadoNovedad).mockResolvedValue({ ...borrador, estado: 'PUBLICADO' })

    renderWithProviders(<NovedadesAdmin />, {
      path: '/cms/novedades',
      user: { ...ESCRIBANO, permissions: ['cms:publish'] },
    })

    fireEvent.click(await screen.findByRole('button', { name: 'Publicar' }))
    await waitFor(() => {
      expect(apiModule.estadoNovedad).toHaveBeenCalledWith('n1', 'PUBLICADO')
    })
  })
})

describe('armado de la portada', () => {
  it('elige distribución y notas, y guarda el armado', async () => {
    vi.resetAllMocks()
    const base = {
      resumen: null,
      contenido: 'Contenido.',
      seccion: 'NOVEDADES' as const,
      fecha_publicacion: '2026-10-01T12:00:00Z',
      imagen_url: null,
      imagen_alt: null,
      autor: null,
      created_at: '2026-10-01T12:00:00Z',
      updated_at: '2026-10-01T12:00:00Z',
    }
    vi.mocked(apiModule.fetchNovedades).mockResolvedValue({
      items: [
        { ...base, id: 'n1', slug: 'a', titulo: 'Publicada', estado: 'PUBLICADO' },
        { ...base, id: 'n2', slug: 'b', titulo: 'En borrador', estado: 'BORRADOR' },
      ],
      total: 2,
      page: 1,
      page_size: 100,
    })
    vi.mocked(apiModule.fetchPortada).mockResolvedValue({
      destacadas: [],
      filas: [],
      actualizada: null,
      actualizada_por: null,
    })
    vi.mocked(apiModule.guardarPortada).mockImplementation((data) =>
      Promise.resolve({ ...data, actualizada: '2026-10-28T12:00:00Z', actualizada_por: 'caja@x' }),
    )

    renderWithProviders(<PortadaAdmin />, {
      path: '/cms/portada',
      user: { ...ESCRIBANO, permissions: ['cms:publish'] },
    })

    fireEvent.click(await screen.findByRole('button', { name: 'Agregar destacada' }))
    fireEvent.change(screen.getByLabelText('Nota principal'), { target: { value: 'n1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Agregar fila' }))
    fireEvent.click(screen.getByLabelText(/^2\+2/))
    fireEvent.change(screen.getByLabelText('Espacio 2 · 2 columnas'), { target: { value: 'n2' } })
    expect(screen.getByText(/no está publicada/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Guardar portada' }))

    await waitFor(() => {
      expect(apiModule.guardarPortada).toHaveBeenCalledWith({
        destacadas: ['n1'],
        filas: [{ distribucion: '2+2', notas: [null, 'n2'] }],
      })
    })
    expect(await screen.findByText(/Guardada el/)).toBeInTheDocument()
  })
})
