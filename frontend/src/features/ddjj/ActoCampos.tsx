import { useId, type ReactNode } from 'react'

import { Field } from '../../components/ui/Field'
import { Select } from '../../components/ui/Select'
import type { Problem } from '../../lib/api'
import { CARGO, matriculaTexto, todayIso } from '../padron/labels'
import { naturalezasSugeridas, type ActoForm } from './acto'
import type {
  CategoriaActo,
  DeclaracionDetalle,
  MotivoExencion,
  TipoProtocolo,
  VademecumActo,
} from './api'
import { CATEGORIA, MOTIVO_EXENCION, PROTOCOLO, rangoPeriodo } from './labels'
import { VademecumBuscador } from './VademecumBuscador'
import { useVademecumDelPeriodo, type EleccionVademecum } from './vademecum'

type Clave = keyof ActoForm

/** Qué eligió quien carga, según el formulario. */
function eleccionDe(form: ActoForm, actos: VademecumActo[]): EleccionVademecum | null {
  const acto = actos.find((a) => a.id === form.vademecum_id)
  if (acto) return { tipo: 'vademecum', acto }
  if (form.categoria === 'SIN_EFECTO') return { tipo: 'sin_efecto' }
  return form.fuera_de_vademecum ? { tipo: 'fuera' } : null
}

/** Cambios del formulario al elegir en el buscador. La naturaleza toma el nombre del acto si
 * estaba vacía o era el nombre del acto anterior (no pisa lo que se escribió a mano). */
function alElegir(
  eleccion: EleccionVademecum,
  form: ActoForm,
  actos: VademecumActo[],
): Partial<ActoForm> {
  const anterior = actos.find((a) => a.id === form.vademecum_id)
  const naturalezaLibre = !form.naturaleza.trim() || form.naturaleza === anterior?.nombre
  if (eleccion.tipo === 'vademecum') {
    const { acto } = eleccion
    return {
      vademecum_id: acto.id,
      fuera_de_vademecum: false,
      categoria: acto.categoria,
      motivo_exencion: acto.motivo_exencion ?? '',
      detalle_exencion: '',
      ...(naturalezaLibre && { naturaleza: acto.nombre }),
    }
  }
  const limpio = {
    vademecum_id: '',
    motivo_exencion: '' as const,
    detalle_exencion: '',
    ...(naturalezaLibre && anterior && { naturaleza: '' }),
  }
  if (eleccion.tipo === 'sin_efecto') {
    return { ...limpio, fuera_de_vademecum: false, categoria: 'SIN_EFECTO' }
  }
  return {
    ...limpio,
    fuera_de_vademecum: true,
    categoria: form.categoria === 'SIN_EFECTO' ? 'OTRO_ACTO' : form.categoria,
  }
}

/** Campos de un acto de la DDJJ (carga manual o revisión de una sugerencia). */
export function ActoCampos({
  ddjj,
  form,
  onChange,
  problem,
  pistas = {},
}: {
  ddjj: DeclaracionDetalle
  form: ActoForm
  onChange: (cambio: Partial<ActoForm>) => void
  problem: Problem | null
  /** Ayuda adicional por campo (p. ej. de dónde salió un valor sugerido). */
  pistas?: Partial<Record<Clave, ReactNode>>
}) {
  const { desde, hasta } = rangoPeriodo(ddjj.periodo)
  const hoy = todayIso()
  const listaNaturalezas = useId()
  const partesId = useId()
  const { actos: vademecum } = useVademecumDelPeriodo(ddjj.periodo)
  const conVademecum = vademecum.length > 0
  const eleccion = eleccionDe(form, vademecum)
  // Con vademécum, la categoría solo se elige a mano para un acto que no está en él.
  const eligeCategoria = !conVademecum || form.fuera_de_vademecum
  const conValor = form.categoria === 'ESCRITURA_CON_VALOR'
  const bind = (
    key:
      | 'numero_escritura'
      | 'folio'
      | 'fecha_acto'
      | 'naturaleza'
      | 'base_imponible'
      | 'precio'
      | 'avaluo'
      | 'detalle_exencion',
  ) => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) => {
      onChange({ [key]: e.target.value })
    },
    error: problem?.fieldErrors[key],
  })

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <Select
          label="Escribano"
          value={form.escribano_id}
          onChange={(e) => {
            onChange({ escribano_id: e.target.value })
          }}
          options={[
            ...(form.escribano_id ? [] : [{ value: '', label: 'Elegí el escribano autorizante' }]),
            ...ddjj.escribanos.map((e) => ({
              value: e.id,
              label: `${e.apellido_nombre} · ${CARGO[e.cargo]} · Mat. ${matriculaTexto(e.matricula_numero)}`,
            })),
          ]}
        />
        {pistas.escribano_id && (
          <p className="mt-1.5 text-sm text-ink-muted">{pistas.escribano_id}</p>
        )}
      </div>
      {conVademecum && (
        <div className="sm:col-span-2">
          <VademecumBuscador
            actos={vademecum}
            eleccion={eleccion}
            onElegir={(e) => {
              onChange(alElegir(e, form, vademecum))
            }}
            error={problem?.fieldErrors.vademecum_id}
          />
          {pistas.categoria && <p className="mt-1.5 text-sm text-ink-muted">{pistas.categoria}</p>}
        </div>
      )}
      {eligeCategoria && (
        <div className="sm:col-span-2">
          <Select
            label={conVademecum ? 'Cómo aporta' : 'Tipo de acto'}
            value={form.categoria}
            onChange={(e) => {
              onChange({ categoria: e.target.value as CategoriaActo })
            }}
            options={(Object.keys(CATEGORIA) as CategoriaActo[])
              // Con vademécum, «sin efecto» se elige en el buscador.
              .filter((c) => !conVademecum || c !== 'SIN_EFECTO')
              .map((c) => ({ value: c, label: CATEGORIA[c].label }))}
          />
          <p className="mt-1.5 text-sm text-ink-muted">
            {conVademecum
              ? CATEGORIA[form.categoria].ayuda
              : (pistas.categoria ?? CATEGORIA[form.categoria].ayuda)}
          </p>
        </div>
      )}
      {eligeCategoria && form.categoria === 'EXENTO' && (
        <>
          <div className={form.motivo_exencion === 'OTRO' ? '' : 'sm:col-span-2'}>
            <Select
              label="Motivo de la exención"
              value={form.motivo_exencion}
              onChange={(e) => {
                onChange({ motivo_exencion: e.target.value as MotivoExencion | '' })
              }}
              options={[
                ...(form.motivo_exencion ? [] : [{ value: '', label: 'Elegí el motivo' }]),
                ...(Object.keys(MOTIVO_EXENCION) as MotivoExencion[]).map((m) => ({
                  value: m,
                  label: MOTIVO_EXENCION[m],
                })),
              ]}
            />
          </div>
          {form.motivo_exencion === 'OTRO' && (
            <Field
              label="¿Cuál?"
              maxLength={300}
              placeholder="Motivo de la exención"
              {...bind('detalle_exencion')}
            />
          )}
        </>
      )}
      <div>
        <Select
          label="Protocolo"
          value={form.tipo_protocolo}
          onChange={(e) => {
            onChange({ tipo_protocolo: e.target.value as TipoProtocolo })
          }}
          options={(Object.keys(PROTOCOLO) as TipoProtocolo[]).map((p) => ({
            value: p,
            label: PROTOCOLO[p],
          }))}
        />
        {pistas.tipo_protocolo && (
          <p className="mt-1.5 text-sm text-ink-muted">{pistas.tipo_protocolo}</p>
        )}
      </div>
      <Field
        label="Fecha del acto"
        type="date"
        min={desde}
        max={hasta < hoy ? hasta : hoy}
        className="[&_input]:tabular-nums"
        hint={pistas.fecha_acto}
        {...bind('fecha_acto')}
      />
      <Field
        label="N° de escritura"
        inputMode="numeric"
        className="[&_input]:tabular-nums"
        hint={pistas.numero_escritura}
        {...bind('numero_escritura')}
      />
      <Field
        label="Folio (opcional)"
        inputMode="numeric"
        className="[&_input]:tabular-nums"
        hint={pistas.folio}
        {...bind('folio')}
      />
      <label className="flex min-h-11 cursor-pointer items-start gap-3 sm:col-span-2">
        <input
          type="checkbox"
          checked={form.acto_multiple}
          onChange={(e) => {
            onChange({ acto_multiple: e.target.checked })
          }}
          className="mt-0.5 size-5 shrink-0 cursor-pointer accent-brand-800"
        />
        <span className="text-sm">
          <span className="block font-medium text-ink">Otro acto de la misma escritura</span>
          <span className="block text-ink-muted">
            Por ejemplo, venta e hipoteca en una sola escritura: cargá primero un acto y después
            cada uno de los demás con este mismo número.
          </span>
        </span>
      </label>
      {form.acto_multiple && (
        <fieldset className="sm:col-span-2" aria-describedby={`${partesId}-ayuda`}>
          <legend className="text-sm font-medium text-ink">
            ¿Intervienen solo las mismas partes en todos los actos de esta escritura?
          </legend>
          <div className="mt-1.5 grid gap-2 sm:grid-cols-2">
            {(
              [
                [true, 'Sí, las mismas partes', 'Se aplica la regla de pluralidad de actos.'],
                [false, 'No, hay partes distintas', 'Cada acto aporta lo suyo.'],
              ] as const
            ).map(([valor, titulo, detalle]) => (
              <label
                key={titulo}
                className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-control border px-3 py-2.5 transition-colors duration-150 ease-out-quint ${form.mismas_partes === valor ? 'border-brand-700 bg-brand-50' : 'border-line-strong bg-surface hover:bg-brand-50'}`}
              >
                <input
                  type="radio"
                  name={partesId}
                  checked={form.mismas_partes === valor}
                  onChange={() => {
                    onChange({ mismas_partes: valor })
                  }}
                  className="mt-0.5 size-5 shrink-0 cursor-pointer accent-brand-800"
                />
                <span className="text-sm">
                  <span className="block font-medium text-ink">{titulo}</span>
                  <span className="block text-ink-muted">{detalle}</span>
                </span>
              </label>
            ))}
          </div>
          <p id={`${partesId}-ayuda`} className="mt-1.5 text-sm text-ink-muted">
            Vale para toda la escritura: si ya cargaste otros actos con este número, se actualizan.
          </p>
        </fieldset>
      )}
      <Field
        className="sm:col-span-2"
        label="Naturaleza del acto"
        placeholder="Compraventa, hipoteca, poder general…"
        maxLength={300}
        list={listaNaturalezas}
        autoComplete="off"
        hint={pistas.naturaleza}
        {...bind('naturaleza')}
      />
      <datalist id={listaNaturalezas}>
        {naturalezasSugeridas(ddjj).map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
      {conValor && conVademecum && (
        <>
          <Field
            className="[&_input]:tabular-nums"
            label="Precio ($)"
            inputMode="decimal"
            placeholder="0,00"
            {...bind('precio')}
          />
          <Field
            className="[&_input]:tabular-nums"
            label="Avalúo ($)"
            inputMode="decimal"
            placeholder="0,00"
            {...bind('avaluo')}
          />
          <p className="-mt-2 text-sm text-ink-muted sm:col-span-2">
            El aporte se calcula sobre el mayor de los dos. Cargá al menos uno.
          </p>
        </>
      )}
      {conValor && !conVademecum && (
        <Field
          className="sm:col-span-2 [&_input]:tabular-nums"
          label="Base imponible ($)"
          inputMode="decimal"
          placeholder="0,00"
          hint={pistas.base_imponible ?? 'Valor del acto sobre el que se calcula el aporte.'}
          {...bind('base_imponible')}
        />
      )}
    </div>
  )
}
