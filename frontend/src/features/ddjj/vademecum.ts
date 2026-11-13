import { useQuery } from '@tanstack/react-query'

import { fetchVademecum, type VademecumActo } from './api'
import { rangoPeriodo } from './labels'

/** Vademécum que rige una DDJJ: el vigente el primer día del período (vacío si no hay). */
export function useVademecumDelPeriodo(periodo: string): {
  actos: VademecumActo[]
  cargando: boolean
} {
  const fecha = rangoPeriodo(periodo).desde
  const query = useQuery({
    queryKey: ['ddjj', 'vademecum', fecha],
    queryFn: () => fetchVademecum(fecha),
    staleTime: 5 * 60_000,
  })
  return { actos: query.data ?? [], cargando: query.isPending }
}

/** Elección del buscador: un acto del vademécum o una de las dos salidas fuera de él. */
export type EleccionVademecum =
  { tipo: 'vademecum'; acto: VademecumActo } | { tipo: 'sin_efecto' } | { tipo: 'fuera' }

export const SIN_EFECTO = 'Escritura sin efecto'
export const FUERA = 'No está en el vademécum'

/** Minúsculas y sin tildes, para que «cesion» encuentre «Cesión». */
export function normalizar(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .trim()
}

/** Actos cuyo nombre o sinónimos contienen todas las palabras buscadas. */
export function buscarEnVademecum(actos: VademecumActo[], consulta: string): VademecumActo[] {
  const palabras = normalizar(consulta).split(/\s+/).filter(Boolean)
  if (palabras.length === 0) return actos
  return actos.filter((a) => {
    const texto = normalizar(`${a.nombre} ${a.sinonimos ?? ''}`)
    return palabras.every((p) => texto.includes(p))
  })
}

export function textoDeEleccion(eleccion: EleccionVademecum | null): string {
  if (!eleccion) return ''
  if (eleccion.tipo === 'vademecum') return eleccion.acto.nombre
  return eleccion.tipo === 'sin_efecto' ? SIN_EFECTO : FUERA
}
