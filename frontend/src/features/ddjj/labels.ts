import type { Tone } from '../../components/StatusIndicator'
import type { CategoriaActo, EstadoBoleta, EstadoDDJJ, TipoProtocolo } from './api'

export const ESTADO_DDJJ: Record<EstadoDDJJ, { label: string; tone: Tone }> = {
  BORRADOR: { label: 'Borrador', tone: 'warning' },
  PRESENTADA: { label: 'Presentada', tone: 'success' },
  RECTIFICADA: { label: 'Rectificada', tone: 'unknown' },
}

export const ESTADO_BOLETA: Record<EstadoBoleta, { label: string; tone: Tone }> = {
  PENDIENTE: { label: 'Pendiente de pago', tone: 'warning' },
  PAGADA: { label: 'Pagada', tone: 'success' },
  ANULADA: { label: 'Anulada', tone: 'unknown' },
}

export const CATEGORIA: Record<CategoriaActo, { label: string; ayuda: string }> = {
  ESCRITURA_CON_VALOR: {
    label: 'Escritura con valor',
    ayuda: 'Aporta un porcentaje de la base imponible, con mínimo y tope por escritura.',
  },
  ACTA_O_PODER: { label: 'Acta o poder', ayuda: 'Aporta un monto fijo por acto.' },
  OTRO_ACTO: {
    label: 'Otro acto sin valor',
    ayuda: 'Acto sin base imponible que no es acta ni poder: monto fijo por acto.',
  },
  SIN_EFECTO: {
    label: 'Sin efecto',
    ayuda: 'Escritura que quedó sin efecto: se declara para no dejar huecos y no aporta.',
  },
}

export const PROTOCOLO: Record<TipoProtocolo, string> = {
  GENERAL: 'General',
  AUXILIAR: 'Auxiliar',
}

/** "2026-09" → "09/2026". */
export function formatPeriodo(periodo: string): string {
  return `${periodo.slice(5, 7)}/${periodo.slice(0, 4)}`
}

/** Período en curso según la fecha de San Juan ("2026-10"). */
export function periodoActual(hoy: string): string {
  return hoy.slice(0, 7)
}

/** Mes anterior a un período: el que normalmente se declara. */
export function periodoAnterior(periodo: string): string {
  const anio = Number.parseInt(periodo.slice(0, 4), 10)
  const mes = Number.parseInt(periodo.slice(5, 7), 10)
  const [a, m] = mes === 1 ? [anio - 1, 12] : [anio, mes - 1]
  return `${String(a)}-${String(m).padStart(2, '0')}`
}

/** Primer y último día del período, para acotar las fechas de los actos. */
export function rangoPeriodo(periodo: string): { desde: string; hasta: string } {
  const anio = Number.parseInt(periodo.slice(0, 4), 10)
  const mes = Number.parseInt(periodo.slice(5, 7), 10)
  const ultimo = new Date(Date.UTC(anio, mes, 0)).getUTCDate()
  return { desde: `${periodo}-01`, hasta: `${periodo}-${String(ultimo).padStart(2, '0')}` }
}

/** Código de verificación en grupos de cuatro, como figura impreso en la boleta. */
export function formatCodigo(codigo: string): string {
  return codigo.replace(/(.{4})(?=.)/g, '$1 ')
}

export function registroLabel(r: { numero_registro: number; nombre_fantasia: string | null }) {
  return r.nombre_fantasia
    ? `Registro N° ${String(r.numero_registro)} · ${r.nombre_fantasia}`
    : `Registro N° ${String(r.numero_registro)}`
}

/** Los últimos `n` períodos, del más reciente (el mes en curso) al más antiguo. */
export function ultimosPeriodos(hoy: string, n = 24): string[] {
  const out: string[] = []
  let p = periodoActual(hoy)
  for (let i = 0; i < n; i++) {
    out.push(p)
    p = periodoAnterior(p)
  }
  return out
}
