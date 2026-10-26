import { useQuery } from '@tanstack/react-query'
import { Calculator, ChevronRight, FilePlus2, Settings2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { toProblem } from '../../lib/api'
import { formatMoney, formatPercent } from '../../lib/decimal'
import { useSession } from '../auth/session'
import { fetchPrestamos, type EstadoPrestamo } from './api'
import { ESTADO_PRESTAMO } from './labels'

export function PrestamosPage() {
  const { can } = useSession()
  const navigate = useNavigate()
  const gestiona = can('prestamos:manage')
  const personal = can('prestamos:read_all')
  const [estado, setEstado] = useState<EstadoPrestamo | ''>('')
  const query = useQuery({
    queryKey: ['prestamos', 'lista', estado],
    queryFn: () => fetchPrestamos(estado),
  })

  return (
    <>
      <PageHeader
        title="Préstamos"
        description={
          personal
            ? 'Solicitudes, préstamos vigentes y su cobranza. Cada solicitud la carga una persona y la resuelve otra.'
            : 'Tus préstamos y los que garantizás. Podés simular uno nuevo antes de pedirlo en la Caja.'
        }
      />
      <Panel
        title={personal ? 'Préstamos' : 'Mis préstamos'}
        actions={
          <>
            <Button
              icon={Calculator}
              onClick={() => {
                void navigate('/prestamos/simular')
              }}
            >
              Simular
            </Button>
            {gestiona && (
              <>
                <Button
                  icon={Settings2}
                  onClick={() => {
                    void navigate('/prestamos/lineas')
                  }}
                >
                  Líneas
                </Button>
                <Button
                  variant="primary"
                  icon={FilePlus2}
                  onClick={() => {
                    void navigate('/prestamos/nueva')
                  }}
                >
                  Nueva solicitud
                </Button>
              </>
            )}
          </>
        }
      >
        <div className="grid gap-4 border-b border-line px-5 py-4 sm:grid-cols-2 sm:px-6">
          <Select
            label="Estado"
            value={estado}
            onChange={(e) => {
              setEstado(e.target.value as EstadoPrestamo | '')
            }}
            options={[
              { value: '', label: 'Todos' },
              ...Object.entries(ESTADO_PRESTAMO).map(([value, { label }]) => ({ value, label })),
            ]}
          />
        </div>
        {query.isError && (
          <div className="px-5 py-4 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}
        <ul className="divide-y divide-line" aria-busy={query.isFetching}>
          {query.data?.length === 0 && (
            <li className="px-5 py-10 text-center text-ink-muted sm:px-6">
              {estado ? 'Ningún préstamo en este estado.' : 'Todavía no hay préstamos.'}
            </li>
          )}
          {query.data?.map((p) => {
            const e = ESTADO_PRESTAMO[p.estado]
            return (
              <li key={p.id}>
                <Link
                  to={`/prestamos/${p.id}`}
                  className="group flex items-center gap-4 px-5 py-4 text-ink no-underline hover:bg-brand-50 sm:px-6"
                >
                  <span className="w-14 shrink-0 text-xl font-semibold text-brand-900 tabular-nums">
                    {p.numero}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold text-brand-800 group-hover:underline">
                      {p.escribano.apellido_nombre}
                    </span>
                    <span className="block text-sm text-ink-muted tabular-nums">
                      {p.linea_nombre} · {formatMoney(p.capital)} en {p.cuotas} cuotas · TNA{' '}
                      {formatPercent(p.tna)}
                    </span>
                    {p.estado === 'OTORGADO' && (
                      <span className="block text-sm tabular-nums">
                        <span className="text-ink">
                          {p.cuotas_pagadas} de {p.cuotas} pagadas · saldo{' '}
                          {formatMoney(p.saldo_capital)}
                        </span>
                        {p.cuotas_vencidas > 0 && (
                          <span className="font-semibold text-danger-700">
                            {' '}
                            · {p.cuotas_vencidas}{' '}
                            {p.cuotas_vencidas === 1 ? 'cuota vencida' : 'cuotas vencidas'}
                          </span>
                        )}
                      </span>
                    )}
                  </span>
                  <StatusIndicator tone={e.tone} label={e.label} />
                  <ChevronRight
                    aria-hidden="true"
                    className="hidden size-5 shrink-0 text-ink-subtle group-hover:text-brand-800 sm:block"
                  />
                </Link>
              </li>
            )
          })}
        </ul>
      </Panel>
    </>
  )
}
