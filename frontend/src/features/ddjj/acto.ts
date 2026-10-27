import { normalizeDecimalInput } from '../../lib/decimal'
import type {
  Acto,
  ActoInput,
  CategoriaActo,
  DeclaracionDetalle,
  MotivoExencion,
  TipoProtocolo,
} from './api'
import { rangoPeriodo } from './labels'

/** Valores del formulario de un acto, tal como se tipean. */
export interface ActoForm {
  escribano_id: string
  categoria: CategoriaActo
  tipo_protocolo: TipoProtocolo
  numero_escritura: string
  folio: string
  fecha_acto: string
  naturaleza: string
  base_imponible: string
  /** Otro acto de una escritura ya cargada en esta DDJJ. */
  acto_multiple: boolean
  /** Solo para actos exentos. */
  motivo_exencion: MotivoExencion | ''
  detalle_exencion: string
}

/** Campos de texto del acto (los que puede sugerir la lectura de una minuta). */
export type CampoActo = Exclude<
  keyof ActoForm,
  'acto_multiple' | 'motivo_exencion' | 'detalle_exencion'
>

export function actoVacio(ddjj: DeclaracionDetalle): ActoForm {
  return {
    escribano_id: ddjj.escribanos[0]?.id ?? '',
    categoria: 'ESCRITURA_CON_VALOR',
    tipo_protocolo: 'GENERAL',
    numero_escritura: '',
    folio: '',
    fecha_acto: rangoPeriodo(ddjj.periodo).desde,
    naturaleza: '',
    base_imponible: '',
    acto_multiple: false,
    motivo_exencion: '',
    detalle_exencion: '',
  }
}

export function actoInput(form: ActoForm): ActoInput {
  const conValor = form.categoria === 'ESCRITURA_CON_VALOR'
  const exento = form.categoria === 'EXENTO' && form.motivo_exencion !== ''
  return {
    escribano_id: form.escribano_id,
    categoria: form.categoria,
    tipo_protocolo: form.tipo_protocolo,
    numero_escritura: Number.parseInt(form.numero_escritura, 10),
    folio: form.folio ? Number.parseInt(form.folio, 10) : null,
    fecha_acto: form.fecha_acto,
    naturaleza: form.naturaleza.trim(),
    base_imponible: conValor ? normalizeDecimalInput(form.base_imponible) : '0',
    acto_multiple: form.acto_multiple,
    motivo_exencion: exento ? form.motivo_exencion || null : null,
    detalle_exencion: exento && form.detalle_exencion.trim() ? form.detalle_exencion.trim() : null,
  }
}

export function actoCompleto(form: ActoForm): boolean {
  return Boolean(
    form.escribano_id &&
    /^\d+$/.test(form.numero_escritura) &&
    form.fecha_acto &&
    form.naturaleza.trim().length >= 3 &&
    (form.categoria !== 'ESCRITURA_CON_VALOR' || form.base_imponible.trim() !== '') &&
    (form.categoria !== 'EXENTO' ||
      (form.motivo_exencion !== '' &&
        (form.motivo_exencion !== 'OTRO' || form.detalle_exencion.trim().length >= 3))),
  )
}

// --------------------------------------------------------------------------- carga rápida

/** Naturalezas habituales para autocompletar (además de las ya cargadas en la DDJJ). */
const NATURALEZAS_COMUNES = [
  'Compraventa',
  'Hipoteca',
  'Cancelación de hipoteca',
  'Donación',
  'Poder general',
  'Poder especial',
  'Cesión de derechos',
  'Usufructo',
  'Constitución de sociedad',
  'Acta de constatación',
]

/** El acto más reciente de la DDJJ: el de fecha más cercana a hoy y, en el mismo día, el de
 * número más alto. */
export function ultimoActo(ddjj: DeclaracionDetalle): Acto | undefined {
  return ddjj.actos.reduce<Acto | undefined>((ultimo, a) => {
    if (!ultimo) return a
    if (a.fecha_acto !== ultimo.fecha_acto) return a.fecha_acto > ultimo.fecha_acto ? a : ultimo
    if (a.numero_escritura !== ultimo.numero_escritura)
      return a.numero_escritura > ultimo.numero_escritura ? a : ultimo
    return a.orden_en_escritura > ultimo.orden_en_escritura ? a : ultimo
  }, undefined)
}

function categoriaQueSigue(categoria: CategoriaActo | undefined): CategoriaActo {
  // Un exento o un acto sin efecto son excepciones: el siguiente vuelve a lo habitual.
  return !categoria || categoria === 'EXENTO' || categoria === 'SIN_EFECTO'
    ? 'ESCRITURA_CON_VALOR'
    : categoria
}

function entre(fecha: string, desde: string, hasta: string): string {
  return fecha < desde ? desde : fecha > hasta ? hasta : fecha
}

/** Formulario del próximo acto, completado con lo más probable: mismo escribano, protocolo y
 * fecha que el último acto cargado, y el número de escritura que sigue en el año. */
export function actoSugerido(ddjj: DeclaracionDetalle, hoy: string): ActoForm {
  const vacio = actoVacio(ddjj)
  const ultimo = ultimoActo(ddjj)
  const { desde, hasta } = rangoPeriodo(ddjj.periodo)
  const tipo = ultimo?.tipo_protocolo ?? vacio.tipo_protocolo
  const escribanoVigente = ddjj.escribanos.some((e) => e.id === ultimo?.escribano_id)
  return {
    ...vacio,
    escribano_id: ultimo && escribanoVigente ? ultimo.escribano_id : vacio.escribano_id,
    tipo_protocolo: tipo,
    categoria: categoriaQueSigue(ultimo?.categoria),
    fecha_acto: ultimo?.fecha_acto ?? entre(hoy, desde, hasta),
    numero_escritura: String(ddjj.proximos_numeros[tipo]),
  }
}

/** Después de agregar un acto: el siguiente conserva escribano, protocolo, categoría y fecha, y
 * pasa al número de escritura que sigue. */
export function actoSiguiente(guardado: ActoForm, ddjj: DeclaracionDetalle): ActoForm {
  const numero = Number.parseInt(guardado.numero_escritura, 10)
  const proximo = Math.max(ddjj.proximos_numeros[guardado.tipo_protocolo], numero + 1)
  return {
    ...actoVacio(ddjj),
    escribano_id: guardado.escribano_id,
    tipo_protocolo: guardado.tipo_protocolo,
    categoria: categoriaQueSigue(guardado.categoria),
    fecha_acto: guardado.fecha_acto,
    numero_escritura: String(proximo),
  }
}

/** Naturalezas para autocompletar: primero las más usadas en la DDJJ, después las habituales. */
export function naturalezasSugeridas(ddjj: DeclaracionDetalle): string[] {
  const usos = new Map<string, number>()
  for (const a of ddjj.actos) usos.set(a.naturaleza, (usos.get(a.naturaleza) ?? 0) + 1)
  const propias = [...usos.entries()].sort((a, b) => b[1] - a[1]).map(([n]) => n)
  const vistas = new Set(propias.map((n) => n.toLowerCase()))
  return [...propias, ...NATURALEZAS_COMUNES.filter((n) => !vistas.has(n.toLowerCase()))]
}
