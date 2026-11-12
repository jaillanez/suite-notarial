import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import { formatMoney } from '../../lib/decimal'
import { useSession } from '../auth/session'
import { formatPeriodo } from '../ddjj/labels'
import { asignarRegistro, fetchBoletasSinRegistro, type BoletaSinRegistro } from './api'

const CLAVE = ['migracion', 'boletas-sin-registro']

function Grupo({ nombre, boletas }: { nombre: string; boletas: BoletaSinRegistro[] }) {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const periodos = [...new Set(boletas.map((b) => b.periodo))]
  const [desde, setDesde] = useState(periodos[0] ?? '')
  const [hasta, setHasta] = useState(periodos[periodos.length - 1] ?? '')
  const [registro, setRegistro] = useState('')
  const elegidas = boletas.filter((b) => b.periodo >= desde && b.periodo <= hasta)
  const asignar = useMutation({
    mutationFn: () =>
      asignarRegistro(
        elegidas.map((b) => b.id),
        Number(registro),
      ),
    onSuccess: async () => {
      setRegistro('')
      await queryClient.invalidateQueries({ queryKey: CLAVE })
    },
  })
  const opciones = periodos.map((p) => ({ value: p, label: formatPeriodo(p) }))
  return (
    <li className="px-5 py-4 sm:px-6">
      <p className="font-semibold text-ink">{nombre}</p>
      <p className="text-sm text-ink-muted tabular-nums">
        {boletas.length} {boletas.length === 1 ? 'boleta' : 'boletas'} ·{' '}
        {formatPeriodo(periodos[0] ?? '')}
        {periodos.length > 1 && ` a ${formatPeriodo(periodos[periodos.length - 1] ?? '')}`}
      </p>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink tabular-nums">
        {boletas.map((b) => (
          <li key={b.id}>
            {formatPeriodo(b.periodo)}: {formatMoney(b.importe)}
          </li>
        ))}
      </ul>
      {can('escribanos:write') && (
        <form
          className="mt-3 grid gap-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault()
            asignar.mutate()
          }}
        >
          {asignar.isError && (
            <div className="sm:col-span-4">
              <Alert tone="danger">{toProblem(asignar.error).detail}</Alert>
            </div>
          )}
          <Select
            label="Desde"
            value={desde}
            onChange={(e) => {
              setDesde(e.target.value)
            }}
            options={opciones}
          />
          <Select
            label="Hasta"
            value={hasta}
            onChange={(e) => {
              setHasta(e.target.value)
            }}
            options={opciones}
          />
          <Field
            label="Registro"
            inputMode="numeric"
            value={registro}
            onChange={(e) => {
              setRegistro(e.target.value.replace(/\D/g, ''))
            }}
          />
          <Button
            type="submit"
            variant="primary"
            busy={asignar.isPending}
            busyLabel="Asignando…"
            disabled={!registro || elegidas.length === 0}
          >
            Asignar a {elegidas.length} {elegidas.length === 1 ? 'boleta' : 'boletas'}
          </Button>
        </form>
      )}
    </li>
  )
}

/** Boletas migradas sin registro: la Caja se lo asigna una sola vez (queda auditado). */
export function BoletasSinRegistro() {
  const query = useQuery({ queryKey: CLAVE, queryFn: fetchBoletasSinRegistro })
  const boletas = query.data ?? []
  if (query.isPending || (query.isSuccess && boletas.length === 0)) return null
  const grupos = new Map<string, BoletaSinRegistro[]>()
  for (const b of boletas) {
    const nombre = b.escribano_origen ?? 'Sin nombre en el origen'
    grupos.set(nombre, [...(grupos.get(nombre) ?? []), b])
  }
  return (
    <Panel
      className="mt-6"
      title="Boletas sin registro"
      description="El sistema anterior las trae pagadas pero sin el registro. Se migraron con el nombre de quien pagó; asignales el registro (si cambió de registro, elegí los meses de cada uno). Se asigna una sola vez y queda auditado."
    >
      {query.isError ? (
        <div className="px-5 py-4 sm:px-6">
          <Alert tone="danger">{toProblem(query.error).detail}</Alert>
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {[...grupos].map(([nombre, items]) => (
            <Grupo key={nombre} nombre={nombre} boletas={items} />
          ))}
        </ul>
      )}
    </Panel>
  )
}
