import { normalizeDecimalInput } from '../../lib/decimal'
import type {
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
