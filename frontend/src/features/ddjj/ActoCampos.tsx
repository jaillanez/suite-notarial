import type { ReactNode } from 'react'

import { Field } from '../../components/ui/Field'
import { Select } from '../../components/ui/Select'
import type { Problem } from '../../lib/api'
import { CARGO, todayIso } from '../padron/labels'
import type { ActoForm } from './acto'
import type { CategoriaActo, DeclaracionDetalle, TipoProtocolo } from './api'
import { CATEGORIA, PROTOCOLO, rangoPeriodo } from './labels'

type Clave = keyof ActoForm

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
  const conValor = form.categoria === 'ESCRITURA_CON_VALOR'
  const bind = (
    key: 'numero_escritura' | 'folio' | 'fecha_acto' | 'naturaleza' | 'base_imponible',
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
              label: `${e.apellido_nombre} · ${CARGO[e.cargo]} · Mat. ${String(e.matricula_numero)}`,
            })),
          ]}
        />
        {pistas.escribano_id && (
          <p className="mt-1.5 text-sm text-ink-muted">{pistas.escribano_id}</p>
        )}
      </div>
      <div className="sm:col-span-2">
        <Select
          label="Tipo de acto"
          value={form.categoria}
          onChange={(e) => {
            onChange({ categoria: e.target.value as CategoriaActo })
          }}
          options={(Object.keys(CATEGORIA) as CategoriaActo[]).map((c) => ({
            value: c,
            label: CATEGORIA[c].label,
          }))}
        />
        <p className="mt-1.5 text-sm text-ink-muted">
          {pistas.categoria ?? CATEGORIA[form.categoria].ayuda}
        </p>
      </div>
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
            Por ejemplo, compraventa e hipoteca en una sola escritura: cargá primero un acto y
            después cada uno de los demás con este mismo número. Cada acto lleva su aporte.
          </span>
        </span>
      </label>
      <Field
        className="sm:col-span-2"
        label="Naturaleza del acto"
        placeholder="Compraventa, hipoteca, poder general…"
        maxLength={300}
        hint={pistas.naturaleza}
        {...bind('naturaleza')}
      />
      {conValor && (
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
