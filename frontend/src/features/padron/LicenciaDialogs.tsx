import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { useState } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import {
  anularLicencia,
  guardarPrimeraEscritura,
  iniciarLicencia,
  terminarLicencia,
  type EscribanoDetalle,
  type LicenciaItem,
} from './api'
import { formatDate, todayIso } from './labels'
import {
  PRIMERA_VACIA,
  primeraCompleta,
  primeraInput,
  type PrimeraEscrituraForm,
} from './primeraEscritura'

const orNull = (value: string): string | null => (value.trim() ? value.trim() : null)

function useGuardar(id: string) {
  const queryClient = useQueryClient()
  return async (data: EscribanoDetalle) => {
    queryClient.setQueryData(['escribano', id], data)
    await queryClient.invalidateQueries({ queryKey: ['padron'] })
  }
}

interface Props {
  escribano: EscribanoDetalle
  open: boolean
  onClose: () => void
}

export function PrimeraEscrituraCampos({
  form,
  onChange,
}: {
  form: PrimeraEscrituraForm
  onChange: (f: PrimeraEscrituraForm) => void
}) {
  const bind = (key: keyof PrimeraEscrituraForm) => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) => {
      onChange({ ...form, [key]: e.target.value })
    },
  })
  return (
    <>
      <Field label="Fecha de la primera escritura" type="date" {...bind('fecha')} />
      <Field label="Número de escritura" maxLength={20} {...bind('numero')} />
      <Field
        label="Registro"
        inputMode="numeric"
        hint="Número de registro, aunque hoy esté cerrado."
        className="[&_input]:tabular-nums"
        {...bind('registro')}
      />
      <Field label="Folio (opcional)" maxLength={20} {...bind('folio')} />
    </>
  )
}

export function PrimeraEscrituraDialog({ escribano, open, onClose }: Props) {
  const guardar = useGuardar(escribano.id)
  const actual = escribano.primera_escritura
  const [form, setForm] = useState<PrimeraEscrituraForm>(
    actual
      ? {
          fecha: actual.fecha,
          numero: actual.numero,
          registro: String(actual.registro),
          folio: actual.folio ?? '',
        }
      : PRIMERA_VACIA,
  )
  const [motivo, setMotivo] = useState('')
  const corrige = actual !== null
  const save = useMutation({
    mutationFn: () =>
      guardarPrimeraEscritura(escribano.id, {
        ...primeraInput(form),
        motivo: corrige ? motivo.trim() : null,
      }),
    onSuccess: async (data) => {
      await guardar(data)
      onClose()
    },
  })
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={corrige ? 'Corregir primera escritura' : 'Cargar primera escritura'}
      description="Determina la antigüedad para la jubilación. Verificala contra la copia de la escritura: el cambio queda auditado."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Guardando…"
            disabled={!primeraCompleta(form) || (corrige && motivo.trim().length < 5)}
            onClick={() => {
              save.mutate()
            }}
          >
            {corrige ? 'Guardar corrección' : 'Guardar primera escritura'}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {save.isError && (
          <div className="sm:col-span-2">
            <Alert tone="danger">{toProblem(save.error).detail}</Alert>
          </div>
        )}
        <PrimeraEscrituraCampos form={form} onChange={setForm} />
        {corrige && (
          <TextArea
            label="Motivo de la corrección"
            className="sm:col-span-2"
            value={motivo}
            onChange={(e) => {
              setMotivo(e.target.value)
            }}
            hint="Obligatorio. Mínimo 5 caracteres."
            maxLength={1000}
          />
        )}
      </div>
    </Dialog>
  )
}

export function LicenciaNuevaDialog({ escribano, open, onClose }: Props) {
  const guardar = useGuardar(escribano.id)
  const [desde, setDesde] = useState(todayIso())
  const [hasta, setHasta] = useState('')
  const [motivo, setMotivo] = useState('')
  const [resolucion, setResolucion] = useState('')
  const save = useMutation({
    mutationFn: () =>
      iniciarLicencia(escribano.id, {
        fecha_desde: desde,
        fecha_hasta: hasta || null,
        motivo: motivo.trim(),
        resolucion_respaldo: orNull(resolucion),
      }),
    onSuccess: async (data) => {
      await guardar(data)
      setMotivo('')
      setResolucion('')
      setHasta('')
      onClose()
    },
  })
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Registrar licencia"
      description="La licencia no cambia el estado de la matrícula ni el cargo: el cargo sigue siendo suyo. Si el registro queda a cargo de otro escribano, se designa en Escribano a cargo."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Guardando…"
            disabled={!desde || motivo.trim().length < 5}
            onClick={() => {
              save.mutate()
            }}
          >
            Registrar licencia
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Desde"
            type="date"
            value={desde}
            onChange={(e) => {
              setDesde(e.target.value)
            }}
          />
          <Field
            label="Hasta (opcional)"
            type="date"
            hint="Vacía: sin fecha de regreso."
            value={hasta}
            onChange={(e) => {
              setHasta(e.target.value)
            }}
          />
        </div>
        <TextArea
          label="Motivo"
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
          hint="Obligatorio. Mínimo 5 caracteres."
          maxLength={1000}
        />
        <Field
          label="Resolución (opcional)"
          placeholder="Res. Directorio 145/2026"
          value={resolucion}
          onChange={(e) => {
            setResolucion(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

export function TerminarLicenciaDialog({
  escribano,
  licencia,
  onClose,
}: {
  escribano: EscribanoDetalle
  licencia: LicenciaItem | null
  onClose: () => void
}) {
  const guardar = useGuardar(escribano.id)
  const [fecha, setFecha] = useState(todayIso())
  const save = useMutation({
    mutationFn: () => terminarLicencia(licencia?.id ?? '', fecha),
    onSuccess: async (data) => {
      await guardar(data)
      onClose()
    },
  })
  return (
    <Dialog
      open={licencia !== null}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Terminar licencia"
      description={
        licencia
          ? `Licencia desde el ${formatDate(licencia.fecha_desde)}. Indicá el último día de licencia: vuelve a ejercer al día siguiente.`
          : undefined
      }
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Guardando…"
            disabled={!fecha}
            onClick={() => {
              save.mutate()
            }}
          >
            Terminar licencia
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <Field
          label="Último día de licencia"
          type="date"
          value={fecha}
          onChange={(e) => {
            setFecha(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

export function AnularLicenciaDialog({
  escribano,
  licencia,
  onClose,
}: {
  escribano: EscribanoDetalle
  licencia: LicenciaItem | null
  onClose: () => void
}) {
  const guardar = useGuardar(escribano.id)
  const [motivo, setMotivo] = useState('')
  const save = useMutation({
    mutationFn: () => anularLicencia(licencia?.id ?? '', motivo.trim()),
    onSuccess: async (data) => {
      await guardar(data)
      setMotivo('')
      onClose()
    },
  })
  return (
    <Dialog
      open={licencia !== null}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Anular licencia"
      description="Para una licencia cargada por error. No se borra: queda en la historia, marcada como anulada."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="danger"
            busy={save.isPending}
            busyLabel="Anulando…"
            disabled={motivo.trim().length < 5}
            onClick={() => {
              save.mutate()
            }}
          >
            Anular licencia
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <TextArea
          label="Motivo de la anulación"
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
          hint="Obligatorio. Mínimo 5 caracteres."
          maxLength={1000}
        />
      </div>
    </Dialog>
  )
}
