import { api } from '../../lib/api'

export type TipoColumna =
  'TEXTO' | 'ENTERO' | 'MONEDA' | 'FECHA' | 'FECHA_HORA' | 'PERIODO' | 'CUIT'
export type TipoFiltro = 'PERIODO' | 'FECHA' | 'OPCIONES' | 'TEXTO' | 'ENTERO'

export interface Columna {
  key: string
  label: string
  tipo: TipoColumna
  total: boolean
  visible: boolean
}

export interface Filtro {
  key: string
  label: string
  tipo: TipoFiltro
  opciones: { value: string; label: string }[]
  ayuda: string | null
}

export interface Reporte {
  codigo: string
  titulo: string
  descripcion: string
  sensible: boolean
  columnas: Columna[]
  filtros: Filtro[]
}

/** Importes como texto decimal; fechas en ISO. */
export type Valor = string | number | null

export interface PaginaReporte {
  items: Record<string, Valor>[]
  total: number
  page: number
  page_size: number
  totales: Record<string, Valor>
}

const P = '/v1/reportes'

export async function fetchReportes(): Promise<Reporte[]> {
  return (await api.get<Reporte[]>(P)).data
}

export async function fetchPagina(
  codigo: string,
  filtros: Record<string, string>,
  page: number,
  pageSize: number,
): Promise<PaginaReporte> {
  return (
    await api.get<PaginaReporte>(`${P}/${codigo}`, {
      params: { ...filtros, page, page_size: pageSize },
    })
  ).data
}

/** Descarga la exportación con los mismos filtros de la grilla (queda auditada). */
export async function exportar(
  codigo: string,
  filtros: Record<string, string>,
  formato: 'xlsx' | 'csv',
): Promise<void> {
  const response = await api.get<Blob>(`${P}/${codigo}/export`, {
    params: { ...filtros, formato },
    responseType: 'blob',
    timeout: 120_000,
  })
  const disposition = String(response.headers['content-disposition'] ?? '')
  const nombre = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `${codigo.toLowerCase()}.${formato}`
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = nombre
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
