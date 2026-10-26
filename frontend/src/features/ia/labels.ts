import type { CampoSugerido } from './api'

export type NivelConfianza = 'alta' | 'media' | 'baja'

/** "0.9500" → 95. La confianza no es un importe: alcanza con redondear a entero. */
export function confianzaPct(confianza: string): number {
  const [entero = '0', decimales = ''] = confianza.split('.')
  const basisPoints = Number.parseInt(entero + decimales.padEnd(4, '0').slice(0, 4), 10)
  return Math.round(basisPoints / 100)
}

export function nivelConfianza(confianza: string): NivelConfianza {
  const pct = confianzaPct(confianza)
  if (pct >= 85) return 'alta'
  if (pct >= 60) return 'media'
  return 'baja'
}

export function textoConfianza(confianza: string): string {
  return `confianza ${nivelConfianza(confianza)} (${String(confianzaPct(confianza))} %)`
}

/** Valor sugerido con el formato del formulario, para comparar con lo que la persona dejó. */
export function sugerido(campo: CampoSugerido | undefined): string {
  return campo?.valor ?? ''
}
