import type { PrimeraEscrituraInput } from './api'

/** Campos de la primera escritura tal como se tipean (los usan su diálogo y «Completar datos»). */
export interface PrimeraEscrituraForm {
  fecha: string
  numero: string
  registro: string
  folio: string
}

export const PRIMERA_VACIA: PrimeraEscrituraForm = {
  fecha: '',
  numero: '',
  registro: '',
  folio: '',
}

/** Algo cargado en cualquiera de los campos. */
export function primeraEmpezada(f: PrimeraEscrituraForm): boolean {
  return [f.fecha, f.numero, f.registro, f.folio].some((v) => v.trim() !== '')
}

/** Fecha, número y registro van juntos; el folio es opcional. */
export function primeraCompleta(f: PrimeraEscrituraForm): boolean {
  return Boolean(f.fecha && f.numero.trim() && /^\d+$/.test(f.registro.trim()))
}

export function primeraInput(f: PrimeraEscrituraForm): PrimeraEscrituraInput {
  return {
    fecha: f.fecha,
    numero: f.numero.trim(),
    registro: Number(f.registro.trim()),
    folio: f.folio.trim() ? f.folio.trim() : null,
  }
}
