import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileUp, Upload } from 'lucide-react'
import { useId, useState } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { toProblem } from '../../lib/api'
import { formatDecimal, formatMoney, normalizeDecimalInput } from '../../lib/decimal'
import type { Boleta } from '../ddjj/api'
import { formatDate, todayIso } from '../padron/labels'
import { adjuntarComprobante } from './api'
import { MAX_BYTES, TIPOS_ACEPTADOS, formatTamano } from './labels'

const TIPOS = new Set(TIPOS_ACEPTADOS.split(','))

function ArchivoField({
  archivo,
  error,
  onChange,
}: {
  archivo: File | null
  error?: string
  onChange: (file: File | null) => void
}) {
  const id = useId()
  return (
    <div>
      <span className="block text-sm font-medium text-ink">Comprobante</span>
      <label
        htmlFor={id}
        className={`mt-1.5 flex min-h-20 cursor-pointer items-center gap-3 rounded-control border border-dashed bg-surface-sunken px-4 py-3 transition-colors duration-150 ease-out-quint hover:border-brand-700 hover:bg-brand-50 has-[:focus-visible]:border-action-600 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-action-600 ${error ? 'border-danger-700' : 'border-line-strong'}`}
      >
        <FileUp aria-hidden="true" className="size-6 shrink-0 text-brand-800" strokeWidth={2} />
        <span className="min-w-0 text-sm">
          {archivo ? (
            <>
              <span className="block truncate font-semibold text-ink">{archivo.name}</span>
              <span className="block text-ink-muted tabular-nums">
                {formatTamano(archivo.size)} · Tocá para cambiarlo
              </span>
            </>
          ) : (
            <>
              <span className="block font-semibold text-brand-800">Elegí el archivo</span>
              <span className="block text-ink-muted">PDF, PNG o JPG de hasta 10 MB</span>
            </>
          )}
        </span>
        <input
          id={id}
          type="file"
          accept={TIPOS_ACEPTADOS}
          className="sr-only"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          onChange={(e) => {
            onChange(e.target.files?.[0] ?? null)
          }}
        />
      </label>
      {error && (
        <p id={`${id}-error`} className="mt-1.5 text-sm font-medium text-danger-700">
          {error}
        </p>
      )}
    </div>
  )
}

export function AdjuntarComprobanteDialog({
  boleta,
  open,
  onClose,
}: {
  boleta: Boleta
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const hoy = todayIso()
  const [archivo, setArchivo] = useState<File | null>(null)
  const [form, setForm] = useState({
    fecha_transferencia: hoy,
    numero_operacion: '',
    importe_declarado: formatDecimal(boleta.total_a_pagar),
    banco_origen: '',
  })
  // Lo que el navegador ya sabe del archivo; el servidor vuelve a validar por contenido.
  const errorArchivo =
    archivo && archivo.size > MAX_BYTES
      ? 'Supera los 10 MB.'
      : archivo && archivo.type && !TIPOS.has(archivo.type)
        ? 'Tiene que ser un PDF, PNG o JPG.'
        : undefined
  const save = useMutation({
    mutationFn: () =>
      adjuntarComprobante(boleta.id, {
        archivo: archivo as File,
        fecha_transferencia: form.fecha_transferencia,
        numero_operacion: form.numero_operacion.trim(),
        importe_declarado: normalizeDecimalInput(form.importe_declarado),
        banco_origen: form.banco_origen.trim(),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ddjj', 'declaracion', boleta.ddjj_id] })
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const bind = (key: keyof typeof form) => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) => {
      setForm((f) => ({ ...f, [key]: e.target.value }))
    },
    error: problem?.fieldErrors[key],
  })

  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={`Comprobante de la boleta N° ${String(boleta.numero)}`}
      description={`Total ${formatMoney(boleta.total_a_pagar)}, a pagar hasta el ${formatDate(boleta.fecha_pago)}.`}
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Upload}
            busy={save.isPending}
            busyLabel="Enviando…"
            disabled={
              !archivo ||
              Boolean(errorArchivo) ||
              !form.numero_operacion.trim() ||
              !form.importe_declarado.trim()
            }
            onClick={() => {
              save.mutate()
            }}
          >
            Enviar a Tesorería
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Alert tone="info">
            Adjuntar el comprobante no registra el pago: la boleta figura como pagada cuando
            Tesorería lo confirma contra el extracto bancario.
          </Alert>
        </div>
        {problem && (
          <div className="sm:col-span-2">
            <Alert tone="danger">{problem.detail}</Alert>
          </div>
        )}
        <div className="sm:col-span-2">
          <ArchivoField archivo={archivo} error={errorArchivo} onChange={setArchivo} />
        </div>
        <Field
          label="Fecha de la transferencia"
          type="date"
          className="[&_input]:tabular-nums"
          min={boleta.fecha_emision}
          max={hoy}
          {...bind('fecha_transferencia')}
        />
        <Field
          label="Importe transferido ($)"
          inputMode="decimal"
          className="[&_input]:tabular-nums"
          {...bind('importe_declarado')}
        />
        <Field
          label="N° de operación"
          maxLength={100}
          autoComplete="off"
          hint="Figura en el comprobante del banco."
          className="[&_input]:tabular-nums"
          {...bind('numero_operacion')}
        />
        <Field label="Banco de origen (opcional)" maxLength={100} {...bind('banco_origen')} />
      </div>
    </Dialog>
  )
}
