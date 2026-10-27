import { describe, expect, it } from 'vitest'

import {
  actoCompleto,
  actoInput,
  actoSiguiente,
  actoSugerido,
  naturalezasSugeridas,
  type ActoForm,
} from './acto'
import type { Acto, DeclaracionDetalle } from './api'
import { categoriaDe } from './labels'

const BASE: ActoForm = {
  escribano_id: 'e1',
  categoria: 'EXENTO',
  tipo_protocolo: 'GENERAL',
  numero_escritura: '12',
  folio: '',
  fecha_acto: '2026-09-15',
  naturaleza: 'Compraventa',
  base_imponible: '',
  acto_multiple: false,
  motivo_exencion: '',
  detalle_exencion: '',
}

describe('acto exento', () => {
  it('exige el motivo y, si es otro, el detalle', () => {
    expect(actoCompleto(BASE)).toBe(false)
    expect(actoCompleto({ ...BASE, motivo_exencion: 'CONVENIO_IPV' })).toBe(true)
    expect(actoCompleto({ ...BASE, motivo_exencion: 'OTRO' })).toBe(false)
    expect(actoCompleto({ ...BASE, motivo_exencion: 'OTRO', detalle_exencion: 'Donación' })).toBe(
      true,
    )
  })

  it('envía el motivo solo si el acto es exento', () => {
    const exento = actoInput({ ...BASE, motivo_exencion: 'OTRO', detalle_exencion: ' Donación ' })
    expect(exento).toMatchObject({
      base_imponible: '0',
      motivo_exencion: 'OTRO',
      detalle_exencion: 'Donación',
    })
    // Si se cambia de categoría, el motivo que quedó elegido no viaja.
    const conValor = actoInput({
      ...BASE,
      categoria: 'ESCRITURA_CON_VALOR',
      base_imponible: '1000',
      motivo_exencion: 'CONVENIO_IPV',
    })
    expect(conValor).toMatchObject({ motivo_exencion: null, detalle_exencion: null })
  })

  it('muestra el motivo junto a la categoría', () => {
    expect(
      categoriaDe({ categoria: 'EXENTO', motivo_exencion: 'CONVENIO_IPV', detalle_exencion: null }),
    ).toBe('Exento · Convenio con el IPV')
    expect(
      categoriaDe({ categoria: 'EXENTO', motivo_exencion: 'OTRO', detalle_exencion: 'Donación' }),
    ).toBe('Exento · Donación')
    expect(
      categoriaDe({ categoria: 'ACTA_O_PODER', motivo_exencion: null, detalle_exencion: null }),
    ).toBe('Acta o poder')
  })
})

describe('carga rápida', () => {
  const acto = (cambios: Partial<Acto>): Acto => ({
    id: 'a',
    escribano_id: 'e2',
    escribano: 'Sintético, Adscripto',
    matricula_numero: 202,
    cargo: 'ADSCRIPTO',
    tipo_protocolo: 'GENERAL',
    numero_escritura: 40,
    orden_en_escritura: 1,
    folio: null,
    fecha_acto: '2026-09-10',
    naturaleza: 'Compraventa',
    categoria: 'ESCRITURA_CON_VALOR',
    base_imponible: '1000.00',
    motivo_exencion: null,
    detalle_exencion: null,
    aporte: null,
    vigencia_id: null,
    ...cambios,
  })
  const ddjj = (actos: Acto[]): DeclaracionDetalle =>
    ({
      periodo: '2026-09',
      actos,
      escribanos: [
        { id: 'e1', apellido_nombre: 'Titular', matricula_numero: 101, cargo: 'TITULAR' },
        { id: 'e2', apellido_nombre: 'Adscripto', matricula_numero: 202, cargo: 'ADSCRIPTO' },
      ],
      proximos_numeros: { GENERAL: 43, AUXILIAR: 5 },
    }) as unknown as DeclaracionDetalle

  it('sin actos propone hoy (dentro del período) y el número que sigue en el año', () => {
    const form = actoSugerido(ddjj([]), '2026-10-23')
    expect(form.fecha_acto).toBe('2026-09-30')
    expect(form.numero_escritura).toBe('43')
    expect(form.escribano_id).toBe('e1')
  })

  it('toma la fecha, el escribano y el protocolo del acto más reciente', () => {
    const form = actoSugerido(
      ddjj([
        acto({ fecha_acto: '2026-09-20', numero_escritura: 42, naturaleza: 'Hipoteca' }),
        acto({ fecha_acto: '2026-09-05', numero_escritura: 41 }),
      ]),
      '2026-10-23',
    )
    expect(form.fecha_acto).toBe('2026-09-20')
    expect(form.escribano_id).toBe('e2')
    expect(form.numero_escritura).toBe('43')
    expect(form.naturaleza).toBe('')
  })

  it('después de un exento vuelve a escritura con valor', () => {
    const form = actoSugerido(
      ddjj([acto({ categoria: 'EXENTO', motivo_exencion: 'CONVENIO_IPV' })]),
      '2026-10-23',
    )
    expect(form.categoria).toBe('ESCRITURA_CON_VALOR')
  })

  it('el siguiente acto pasa al número que sigue al guardado', () => {
    const siguiente = actoSiguiente(
      { ...BASE, categoria: 'ACTA_O_PODER', numero_escritura: '50' },
      ddjj([]),
    )
    expect(siguiente.numero_escritura).toBe('51')
    expect(siguiente.categoria).toBe('ACTA_O_PODER')
    expect(siguiente.fecha_acto).toBe(BASE.fecha_acto)
    expect(siguiente.naturaleza).toBe('')
  })

  it('autocompleta primero con las naturalezas más usadas', () => {
    const lista = naturalezasSugeridas(
      ddjj([acto({ naturaleza: 'Hipoteca' }), acto({ naturaleza: 'Hipoteca' }), acto({})]),
    )
    expect(lista.slice(0, 2)).toEqual(['Hipoteca', 'Compraventa'])
    expect(lista.filter((n) => n === 'Hipoteca')).toHaveLength(1)
  })
})
