import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'

import { normalizeDecimalInput } from '../../lib/decimal'
import type { ActoForm } from './acto'
import { verificarActo, type VerificacionActoInput } from './api'

const PAUSA_MS = 400

function entero(valor: string): number | null {
  return /^\d+$/.test(valor.trim()) ? Number.parseInt(valor, 10) : null
}

/** Lo que haya cargado del acto, en el formato de la API (sin pasar importes por float). */
export function datosAVerificar(form: ActoForm, excluir?: string): VerificacionActoInput {
  const base = normalizeDecimalInput(form.base_imponible)
  return {
    tipo_protocolo: form.tipo_protocolo,
    numero_escritura: entero(form.numero_escritura),
    folio: entero(form.folio),
    fecha_acto: /^\d{4}-\d{2}-\d{2}$/.test(form.fecha_acto) ? form.fecha_acto : null,
    categoria: form.categoria,
    base_imponible:
      form.categoria === 'ESCRITURA_CON_VALOR' && /^\d+(\.\d{1,2})?$/.test(base) ? base : null,
    excluir_acto_id: excluir ?? null,
  }
}

/**
 * Aporte estimado y controles del libro de protocolo mientras se carga un acto. Consulta al
 * servidor después de una pausa al tipear; el servidor vuelve a controlar al guardar.
 */
export function useVerificacionActo(ddjjId: string, form: ActoForm, excluir?: string) {
  const datos = useMemo(() => datosAVerificar(form, excluir), [form, excluir])
  const [enviado, setEnviado] = useState(datos)
  useEffect(() => {
    const espera = setTimeout(() => {
      setEnviado(datos)
    }, PAUSA_MS)
    return () => {
      clearTimeout(espera)
    }
  }, [datos])
  const query = useQuery({
    queryKey: ['ddjj', 'verificacion', ddjjId, enviado],
    queryFn: () => verificarActo(ddjjId, enviado),
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  })
  return {
    verificacion: query.data,
    bloqueado: query.data?.controles.some((c) => c.nivel === 'BLOQUEANTE') ?? false,
    actualizando: query.isFetching || enviado !== datos,
  }
}
