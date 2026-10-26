import { api } from '../../lib/api'

export type EstadoPublicacion = 'BORRADOR' | 'PUBLICADO' | 'ARCHIVADO'
export type TipoDocumento = 'ESTADO_CONTABLE' | 'MEMORIA_ANUAL' | 'RESOLUCION' | 'OTRO'

export interface Autoridad {
  id: string
  cargo: string
  nombre: string
  orden: number
  mandato_desde: string | null
  mandato_hasta: string | null
  is_active: boolean
}

export interface AutoridadInput {
  cargo: string
  nombre: string
  orden: number
  mandato_desde: string | null
  mandato_hasta: string | null
  is_active?: boolean
}

export interface Novedad {
  id: string
  slug: string
  titulo: string
  resumen: string | null
  contenido: string
  estado: EstadoPublicacion
  fecha_publicacion: string | null
  autor: string | null
  created_at: string
  updated_at: string
}

export interface NovedadInput {
  titulo: string
  resumen: string | null
  contenido: string
  slug: string | null
}

export interface Version {
  version: number
  nombre_original: string
  sha256: string
  tamano_bytes: number
  paginas: number
  motivo: string | null
  subido_por: string | null
  created_at: string
  url: string
  integra: boolean | null
}

export interface Documento {
  id: string
  slug: string
  tipo: TipoDocumento
  ejercicio: number
  titulo: string
  descripcion: string | null
  estado: EstadoPublicacion
  fecha_publicacion: string | null
  url: string
  versiones: Version[]
}

interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

const P = '/v1/cms'

export async function fetchAutoridades(): Promise<Autoridad[]> {
  return (await api.get<Autoridad[]>(`${P}/autoridades`)).data
}

export async function crearAutoridad(data: AutoridadInput): Promise<Autoridad> {
  return (await api.post<Autoridad>(`${P}/autoridades`, data)).data
}

export async function actualizarAutoridad(id: string, data: AutoridadInput): Promise<Autoridad> {
  return (await api.put<Autoridad>(`${P}/autoridades/${id}`, data)).data
}

export async function fetchNovedades(params: {
  page: number
  pageSize: number
  estado: EstadoPublicacion | ''
}): Promise<Page<Novedad>> {
  return (
    await api.get<Page<Novedad>>(`${P}/novedades`, {
      params: {
        page: params.page,
        page_size: params.pageSize,
        estado: params.estado || undefined,
      },
    })
  ).data
}

export async function crearNovedad(data: NovedadInput): Promise<Novedad> {
  return (await api.post<Novedad>(`${P}/novedades`, data)).data
}

export async function actualizarNovedad(id: string, data: NovedadInput): Promise<Novedad> {
  return (await api.put<Novedad>(`${P}/novedades/${id}`, data)).data
}

export async function estadoNovedad(id: string, estado: EstadoPublicacion): Promise<Novedad> {
  return (await api.post<Novedad>(`${P}/novedades/${id}/estado`, { estado })).data
}

export async function fetchDocumentos(): Promise<Documento[]> {
  return (await api.get<Documento[]>(`${P}/documentos`)).data
}

/** Detalle con la verificación de huella de cada versión. */
export async function fetchDocumento(id: string): Promise<Documento> {
  return (await api.get<Documento>(`${P}/documentos/${id}`)).data
}

export async function crearDocumento(data: {
  tipo: TipoDocumento
  ejercicio: string
  titulo: string
  descripcion: string
  archivo: File
}): Promise<Documento> {
  const form = new FormData()
  form.append('tipo', data.tipo)
  form.append('ejercicio', data.ejercicio)
  form.append('titulo', data.titulo)
  if (data.descripcion) form.append('descripcion', data.descripcion)
  form.append('archivo', data.archivo)
  return (await api.post<Documento>(`${P}/documentos`, form, { timeout: 120_000 })).data
}

export async function nuevaVersion(id: string, motivo: string, archivo: File): Promise<Documento> {
  const form = new FormData()
  form.append('motivo', motivo)
  form.append('archivo', archivo)
  return (await api.post<Documento>(`${P}/documentos/${id}/versiones`, form, { timeout: 120_000 }))
    .data
}

export async function estadoDocumento(id: string, estado: EstadoPublicacion): Promise<Documento> {
  return (await api.post<Documento>(`${P}/documentos/${id}/estado`, { estado })).data
}

// --------------------------------------------------------------------------- sitio público

export interface NovedadResumen {
  slug: string
  titulo: string
  resumen: string | null
  fecha_publicacion: string
}

export interface NovedadPublica extends NovedadResumen {
  contenido: string
}

/** Versión anterior en el sitio público: sin nombres de archivo ni usuarios internos. */
export interface VersionPublica {
  version: number
  sha256: string
  tamano_bytes: number
  paginas: number
  motivo: string | null
  created_at: string
  url: string
}

export interface DocumentoPublico {
  slug: string
  tipo: TipoDocumento
  tipo_texto: string
  ejercicio: number
  titulo: string
  descripcion: string | null
  fecha_publicacion: string
  url: string
  paginas: number
  tamano_bytes: number
  sha256: string
  version: number
  actualizado: string
  motivo_actualizacion: string | null
  versiones_anteriores: VersionPublica[]
}

export interface Sitio {
  autoridades: Autoridad[]
  novedades: NovedadResumen[]
  documentos: DocumentoPublico[]
}

export async function fetchSitio(): Promise<Sitio> {
  return (await api.get<Sitio>('/v1/publico/sitio')).data
}

export async function fetchNovedadesPublicas(page: number): Promise<Page<NovedadResumen>> {
  return (
    await api.get<Page<NovedadResumen>>('/v1/publico/novedades', {
      params: { page, page_size: 10 },
    })
  ).data
}

export async function fetchNovedadPublica(slug: string): Promise<NovedadPublica> {
  return (await api.get<NovedadPublica>(`/v1/publico/novedades/${encodeURIComponent(slug)}`)).data
}
