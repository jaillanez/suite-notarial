import { formatDecimal } from '../../lib/decimal'
import { actoVacio, type ActoForm, type CampoActo } from '../ddjj/acto'
import type { CategoriaActo, DeclaracionDetalle, TipoProtocolo } from '../ddjj/api'
import type { Sugerencia } from './api'

/** Formulario de un acto a partir de lo que propuso el motor. `escribanoPorDefecto` se usa si
 * la sugerencia no identificó al autorizante (el índice no lo dice; la minuta, a veces). */
export function formularioDe(
  ddjj: DeclaracionDetalle,
  s: Sugerencia,
  escribanoPorDefecto = '',
): ActoForm {
  const v = (k: CampoActo) => s.campos[k]?.valor ?? null
  const vacio = actoVacio(ddjj)
  const escribano = v('escribano_id')
  const base = v('base_imponible')
  return {
    escribano_id:
      escribano && ddjj.escribanos.some((e) => e.id === escribano)
        ? escribano
        : escribanoPorDefecto,
    categoria: (v('categoria') ?? vacio.categoria) as CategoriaActo,
    tipo_protocolo: (v('tipo_protocolo') ?? vacio.tipo_protocolo) as TipoProtocolo,
    numero_escritura: v('numero_escritura') ?? '',
    folio: v('folio') ?? '',
    fecha_acto: v('fecha_acto') ?? '',
    naturaleza: v('naturaleza') ?? '',
    base_imponible: base && base !== '0.00' ? formatDecimal(base) : '',
    acto_multiple: false,
    motivo_exencion: '',
    detalle_exencion: '',
  }
}
