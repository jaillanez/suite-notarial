import { describe, expect, it } from 'vitest'

import { actoCompleto, actoInput, type ActoForm } from './acto'
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
