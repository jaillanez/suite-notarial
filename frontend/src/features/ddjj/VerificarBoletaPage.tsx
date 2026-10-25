import { useQuery } from '@tanstack/react-query'
import { ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { formatMoney } from '../../lib/decimal'
import { formatDate } from '../padron/labels'
import { verificarBoleta } from './api'
import { ESTADO_BOLETA, formatCodigo, formatPeriodo } from './labels'

const CODIGO_RE = /^[A-Z2-7]{16}$/

/** El código impreso va en grupos de cuatro; se acepta con espacios, guiones o minúsculas. */
function normalizarCodigo(value: string): string {
  return value.toUpperCase().replace(/[\s-]/g, '')
}

function Par({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 py-3 sm:px-6">
      <dt className="text-sm font-medium text-ink-muted">{label}</dt>
      <dd className="text-ink tabular-nums">{value}</dd>
    </div>
  )
}

function Resultado({ codigo }: { codigo: string }) {
  const query = useQuery({
    queryKey: ['verificar', codigo],
    queryFn: () => verificarBoleta(codigo),
    retry: false,
  })
  if (query.isPending) {
    return (
      <div aria-busy="true" aria-live="polite" className="grid gap-3">
        <span className="block h-8 w-56 animate-pulse rounded-control bg-brand-50" />
        <span className="block h-48 animate-pulse rounded-panel bg-brand-50" />
      </div>
    )
  }
  if (query.isError) {
    const problem = toProblem(query.error)
    return (
      <Alert tone="danger" title="No encontramos esa boleta">
        {problem.status === 404 || problem.status === 422
          ? 'Revisá el código impreso debajo del QR. Si es correcto y la boleta no figura, no fue emitida por la Caja.'
          : problem.detail}
      </Alert>
    )
  }
  const b = query.data
  const estado = ESTADO_BOLETA[b.estado]
  return (
    <div aria-live="polite" className="grid gap-4">
      {b.integra ? (
        <Alert tone="success" title="Boleta auténtica">
          Fue emitida por la Caja Notarial de San Juan y sus datos coinciden con los registrados.
        </Alert>
      ) : (
        <Alert tone="danger" title="Los datos de la boleta no coinciden">
          La boleta existe pero su registro no supera el control de integridad. No la uses para
          pagar y comunicate con la Caja.
        </Alert>
      )}
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
          <p className="text-lg font-semibold text-ink tabular-nums">Boleta N° {b.numero}</p>
          <StatusIndicator tone={estado.tone} label={estado.label} />
        </div>
        <dl className="divide-y divide-line">
          <Par label="Registro notarial" value={`N° ${String(b.registro_numero)}`} />
          <Par label="Período" value={formatPeriodo(b.periodo)} />
          <Par label="Emitida el" value={formatDate(b.fecha_emision)} />
          <Par label="Pagar hasta" value={formatDate(b.fecha_pago)} />
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t border-line-strong px-5 py-4 sm:px-6">
            <dt className="font-semibold text-brand-900">Total a pagar</dt>
            <dd className="text-xl font-semibold text-brand-900 tabular-nums">
              {formatMoney(b.total_a_pagar)}
            </dd>
          </div>
        </dl>
        <p className="border-t border-line bg-surface-sunken px-5 py-3 text-xs text-ink-muted tabular-nums sm:px-6">
          Código {formatCodigo(b.codigo_verificacion)}
        </p>
      </Panel>
      {b.estado === 'ANULADA' && (
        <Alert tone="warning">
          Esta boleta fue reemplazada por otra. Pagá con la boleta vigente.
        </Alert>
      )}
    </div>
  )
}

export function VerificarBoletaPage() {
  const { codigo: param = '' } = useParams()
  const navigate = useNavigate()
  const codigo = normalizarCodigo(param)
  const [entrada, setEntrada] = useState(formatCodigo(codigo))
  const normalizado = normalizarCodigo(entrada)
  const valido = CODIGO_RE.test(normalizado)

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-brand-900">Verificar boleta</h1>
        <p className="mt-2 text-ink-muted">
          Comprobá que una boleta de aportes fue emitida por la Caja Notarial de San Juan y que sus
          datos no fueron alterados.
        </p>
      </div>
      <form
        className="flex flex-col gap-3 sm:flex-row sm:items-end"
        onSubmit={(e) => {
          e.preventDefault()
          if (valido) void navigate(`/verificar/${normalizado}`)
        }}
      >
        <Field
          className="flex-1 [&_input]:font-medium [&_input]:tracking-wider [&_input]:tabular-nums"
          label="Código de verificación"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          placeholder="XXXX XXXX XXXX XXXX"
          hint="Figura debajo del QR, en cuatro grupos de cuatro caracteres."
          value={entrada}
          onChange={(e) => {
            setEntrada(e.target.value)
          }}
        />
        <Button
          type="submit"
          variant="primary"
          icon={ShieldCheck}
          disabled={!valido}
          className="sm:mb-[1.875rem]"
        >
          Verificar
        </Button>
      </form>
      {codigo && CODIGO_RE.test(codigo) && <Resultado key={codigo} codigo={codigo} />}
    </div>
  )
}
