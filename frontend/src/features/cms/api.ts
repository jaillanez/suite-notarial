import { api } from '../../lib/api'

export type EstadoPublicacion = 'BORRADOR' | 'PUBLICADO' | 'ARCHIVADO'
export type TipoDocumento = 'ESTADO_CONTABLE' | 'MEMORIA_ANUAL' | 'RESOLUCION' | 'OTRO'
export type SeccionNovedad = 'NOVEDADES' | 'COMUNICADOS' | 'APORTES' | 'INSTITUCIONAL'
export type GrupoPagina = 'CAJA' | 'NORMATIVA'
export type Distribucion = '4' | '3+1' | '2+2' | '2+1+1' | '1+1+1+1'

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
  seccion: SeccionNovedad
  estado: EstadoPublicacion
  fecha_publicacion: string | null
  imagen_url: string | null
  imagen_alt: string | null
  autor: string | null
  created_at: string
  updated_at: string
}

export interface NovedadInput {
  titulo: string
  resumen: string | null
  seccion: SeccionNovedad
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
  seccion: SeccionNovedad
  seccion_texto: string
  fecha_publicacion: string
  imagen_url: string | null
  imagen_alt: string | null
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

export interface FilaPublica {
  distribucion: Distribucion
  notas: NovedadResumen[]
}

export interface PaginaMenu {
  slug: string
  grupo: GrupoPagina
  titulo: string
}

export interface PaginaPublica extends PaginaMenu {
  grupo_texto: string
  contenido: string
  updated_at: string
}

export interface Contacto {
  nombre: string
  domicilio: string | null
  telefono: string | null
  email: string | null
}

export interface Sitio {
  portada: { destacadas: NovedadResumen[]; filas: FilaPublica[] }
  menu: PaginaMenu[]
  contacto: Contacto
  autoridades: Autoridad[]
  novedades: NovedadResumen[]
  documentos: DocumentoPublico[]
}

export async function fetchSitio(): Promise<Sitio> {
  return (await api.get<Sitio>('/v1/publico/sitio')).data
}

export async function fetchNovedadesPublicas(
  page: number,
  seccion: SeccionNovedad | null = null,
): Promise<Page<NovedadResumen>> {
  return (
    await api.get<Page<NovedadResumen>>('/v1/publico/novedades', {
      params: { page, page_size: 12, ...(seccion ? { seccion } : {}) },
    })
  ).data
}

export async function fetchPaginaPublica(slug: string): Promise<PaginaPublica> {
  return (await api.get<PaginaPublica>(`/v1/publico/paginas/${encodeURIComponent(slug)}`)).data
}

export async function fetchNovedadPublica(slug: string): Promise<NovedadPublica> {
  return (await api.get<NovedadPublica>(`/v1/publico/novedades/${encodeURIComponent(slug)}`)).data
}

// --------------------------------------------------------------------------- imagen, páginas y portada

export async function subirImagen(id: string, archivo: File, alt: string): Promise<Novedad> {
  const form = new FormData()
  form.append('alt', alt)
  form.append('archivo', archivo)
  return (await api.post<Novedad>(`${P}/novedades/${id}/imagen`, form)).data
}

export async function quitarImagen(id: string): Promise<Novedad> {
  return (await api.post<Novedad>(`${P}/novedades/${id}/imagen/quitar`)).data
}

export interface Pagina {
  id: string
  slug: string
  grupo: GrupoPagina
  titulo: string
  contenido: string
  orden: number
  estado: EstadoPublicacion
  updated_at: string
}

export interface PaginaInput {
  grupo: GrupoPagina
  titulo: string
  contenido: string
  orden: number
  slug: string | null
}

export async function fetchPaginas(): Promise<Pagina[]> {
  return (await api.get<Pagina[]>(`${P}/paginas`)).data
}

export async function crearPagina(data: PaginaInput): Promise<Pagina> {
  return (await api.post<Pagina>(`${P}/paginas`, data)).data
}

export async function actualizarPagina(id: string, data: PaginaInput): Promise<Pagina> {
  return (await api.put<Pagina>(`${P}/paginas/${id}`, data)).data
}

export async function estadoPagina(id: string, estado: EstadoPublicacion): Promise<Pagina> {
  return (await api.post<Pagina>(`${P}/paginas/${id}/estado`, { estado })).data
}

export interface FilaPortada {
  distribucion: Distribucion
  /** Una nota por espacio; null deja el espacio libre. */
  notas: (string | null)[]
}

export interface Portada {
  destacadas: string[]
  filas: FilaPortada[]
  actualizada: string | null
  actualizada_por: string | null
}

export async function fetchPortada(): Promise<Portada> {
  return (await api.get<Portada>(`${P}/portada`)).data
}

export async function guardarPortada(
  data: Pick<Portada, 'destacadas' | 'filas'>,
): Promise<Portada> {
  return (await api.put<Portada>(`${P}/portada`, data)).data
}
