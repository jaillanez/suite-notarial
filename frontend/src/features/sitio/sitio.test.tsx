import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as apiModule from '../cms/api'
import { NovedadesAdmin } from '../cms/NovedadesAdmin'
import { parrafos, rutaLocal } from '../cms/labels'
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

  it('muestra documentos con descarga, versión vigente, motivo e historial', async () => {
    vi.mocked(apiModule.fetchSitio).mockResolvedValue({
      autoridades: [
        {
          id: 'a1',
          cargo: 'Presidente',
          nombre: 'Esc. Demo',
          orden: 1,
          mandato_desde: null,
          mandato_hasta: null,
          is_active: true,
        },
      ],
      novedades: [],
      documentos: [DOC],
    })

    renderWithProviders(<SitioPage />, { path: '/sitio' })

    expect(await screen.findByText('Estados contables al 31 de diciembre')).toBeInTheDocument()
    expect(screen.getByText('Presidente')).toBeInTheDocument()
    expect(screen.getByText('Motivo: Se corrigió la nota 4.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Descargar PDF/ })).toHaveAttribute(
      'href',
      '/api/v1/publico/documentos/estados-contables-2025.pdf',
    )
    expect(screen.getByRole('link', { name: 'Versión 1' })).toBeInTheDocument()
  })

  it('el contenido de una novedad se muestra como texto, nunca como HTML', async () => {
    vi.mocked(apiModule.fetchNovedadPublica).mockResolvedValue({
      slug: 'n',
      titulo: 'Novedad',
      resumen: null,
      fecha_publicacion: '2026-10-25T12:00:00Z',
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
      estado: 'BORRADOR',
      fecha_publicacion: null,
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
