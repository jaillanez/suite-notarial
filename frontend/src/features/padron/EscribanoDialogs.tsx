import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { useState } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import {
  createCuenta,
  assignCargo,
  changeEstado,
  closeCargo,
  fetchRegistros,
  updateEscribano,
  type Cargo,
  type CargoItem,
  type EscribanoDetalle,
  type EstadoMatricula,
} from './api'
import { CARGO, ESTADO_MATRICULA, ESTADOS_DEFINITIVOS, todayIso } from './labels'

const orNull = (value: string): string | null => (value.trim() ? value.trim() : null)

interface Props {
  escribano: EscribanoDetalle
  open: boolean
  onClose: () => void
}

function useRefresh(id: string) {
  const queryClient = useQueryClient()
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['padron'] })
    await queryClient.invalidateQueries({ queryKey: ['escribano', id] })
  }
}

export function EstadoDialog({ escribano, open, onClose }: Props) {
  const refresh = useRefresh(escribano.id)
  const opciones = escribano.transiciones_permitidas
  const [estado, setEstado] = useState<EstadoMatricula>(opciones[0] ?? 'ACTIVO')
  const [motivo, setMotivo] = useState('')
  const [resolucion, setResolucion] = useState('')
  const [fecha, setFecha] = useState(todayIso())
  const save = useMutation({
    mutationFn: () =>
      changeEstado(escribano.id, {
        nuevo_estado: estado,
        motivo: motivo.trim(),
        resolucion_respaldo: orNull(resolucion),
        fecha_efectiva: fecha,
      }),
    onSuccess: async () => {
      await refresh()
      setMotivo('')
      setResolucion('')
      onClose()
    },
  })
  const definitivo = ESTADOS_DEFINITIVOS.includes(estado)
  const exigeResolucion = escribano.transiciones_con_resolucion.includes(estado)
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Cambiar estado de la matrícula"
      description={`Estado actual: ${ESTADO_MATRICULA[escribano.estado_matricula].label}. El cambio queda en el historial y no se puede borrar.`}
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant={estado === 'ACTIVO' ? 'primary' : 'danger'}
            icon={Save}
            busy={save.isPending}
            busyLabel="Guardando…"
            disabled={motivo.trim().length < 5 || !fecha || (exigeResolucion && !resolucion.trim())}
            onClick={() => {
              save.mutate()
            }}
          >
            Cambiar a {ESTADO_MATRICULA[estado].label.toLowerCase()}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <Select
          label="Nuevo estado"
          value={estado}
          onChange={(e) => {
            setEstado(e.target.value as EstadoMatricula)
          }}
          options={opciones.map((e) => ({ value: e, label: ESTADO_MATRICULA[e].label }))}
        />
        {definitivo && (
          <Alert tone="warning">
            {estado === 'FALLECIDO'
              ? 'Fallecido es un estado definitivo: después no admite cambios.'
              : estado === 'JUBILADO'
                ? 'Un jubilado no vuelve a ejercer por cambio de estado. Si tiene un cargo vigente, cerralo antes.'
                : 'Es una baja del ejercicio: la cuenta de autogestión se suspende. Si tiene un cargo vigente, cerralo antes.'}
          </Alert>
        )}
        {estado === 'SUSPENDIDO' && (
          <Alert tone="info">
            Mientras dure la suspensión, su cuenta queda en solo consulta: no puede presentar
            declaraciones juradas.
          </Alert>
        )}
        <TextArea
          label="Motivo"
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
          hint="Obligatorio. Mínimo 5 caracteres."
          maxLength={1000}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={exigeResolucion ? 'Resolución' : 'Resolución (opcional)'}
            hint={exigeResolucion ? 'Obligatoria para la reincorporación.' : undefined}
            placeholder="Res. Directorio 145/2026"
            value={resolucion}
            onChange={(e) => {
              setResolucion(e.target.value)
            }}
          />
          <Field
            label="Fecha efectiva"
            type="date"
            value={fecha}
            onChange={(e) => {
              setFecha(e.target.value)
            }}
          />
        </div>
      </div>
    </Dialog>
  )
}

export function AsignarCargoDialog({ escribano, open, onClose }: Props) {
  const refresh = useRefresh(escribano.id)
  const registros = useQuery({
    queryKey: ['padron', 'registros', 'abiertos'],
    queryFn: () => fetchRegistros({ page: 1, pageSize: 100, q: '', departamento: '', estado: '' }),
    enabled: open,
  })
  const abiertos = (registros.data?.items ?? []).filter((r) => r.estado !== 'CERRADO')
  const [registroId, setRegistroId] = useState('')
  const [cargo, setCargo] = useState<Cargo>('ADSCRIPTO')
  const [fecha, setFecha] = useState(todayIso())
  const [resolucion, setResolucion] = useState('')
  const elegido = registroId || abiertos[0]?.id || ''
  const save = useMutation({
    mutationFn: () =>
      assignCargo(escribano.id, {
        registro_id: elegido,
        cargo,
        fecha_desde: fecha,
        resolucion_designacion: orNull(resolucion),
      }),
    onSuccess: async () => {
      await refresh()
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
      title="Asignar cargo en un registro"
      description="Un registro tiene un solo titular vigente; un escribano, un solo cargo vigente."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Asignando…"
            disabled={!elegido || !fecha}
            onClick={() => {
              save.mutate()
            }}
          >
            Asignar cargo
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <Select
          label="Registro notarial"
          value={elegido}
          onChange={(e) => {
            setRegistroId(e.target.value)
          }}
          options={abiertos.map((r) => ({
            value: r.id,
            label: `Nº ${String(r.numero_registro)} · ${r.departamento}${r.titular ? '' : ' · vacante'}`,
          }))}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label="Cargo"
            value={cargo}
            onChange={(e) => {
              setCargo(e.target.value as Cargo)
            }}
            options={(Object.keys(CARGO) as Cargo[]).map((c) => ({ value: c, label: CARGO[c] }))}
          />
          <Field
            label="Desde"
            type="date"
            value={fecha}
            onChange={(e) => {
              setFecha(e.target.value)
            }}
          />
        </div>
        <Field
          label="Resolución de designación (opcional)"
          value={resolucion}
          onChange={(e) => {
            setResolucion(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

export function CerrarCargoDialog({
  escribano,
  cargo,
  onClose,
}: {
  escribano: EscribanoDetalle
  cargo: CargoItem | null
  onClose: () => void
}) {
  const refresh = useRefresh(escribano.id)
  const [fecha, setFecha] = useState(todayIso())
  const [motivo, setMotivo] = useState('')
  const save = useMutation({
    mutationFn: () => closeCargo(cargo?.id ?? '', fecha, motivo.trim()),
    onSuccess: async () => {
      await refresh()
      setMotivo('')
      onClose()
    },
  })
  return (
    <Dialog
      open={cargo !== null}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={
        cargo
          ? `Cerrar cargo de ${CARGO[cargo.cargo].toLowerCase()} en el Registro ${String(cargo.numero_registro)}`
          : 'Cerrar cargo'
      }
      description={
        cargo?.cargo === 'TITULAR'
          ? 'El registro quedará vacante hasta que se designe un nuevo titular.'
          : 'El cargo queda en el historial con su fecha de cierre.'
      }
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="danger"
            busy={save.isPending}
            busyLabel="Cerrando…"
            disabled={motivo.trim().length < 5 || !fecha}
            onClick={() => {
              save.mutate()
            }}
          >
            Cerrar cargo
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <Field
          label="Fecha de cierre"
          type="date"
          value={fecha}
          onChange={(e) => {
            setFecha(e.target.value)
          }}
        />
        <TextArea
          label="Motivo"
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
          hint="Obligatorio. Por ejemplo, la resolución que acepta la renuncia."
        />
      </div>
    </Dialog>
  )
}

export function EditarEscribanoDialog({ escribano, open, onClose }: Props) {
  const refresh = useRefresh(escribano.id)
  const p = escribano.persona
  const [form, setForm] = useState({
    apellido: p.apellido,
    nombre: p.nombre,
    numero_documento: p.numero_documento,
    fecha_nacimiento: p.fecha_nacimiento ?? '',
    email: p.email ?? '',
    telefono: p.telefono ?? '',
    domicilio_real: p.domicilio_real ?? '',
    tomo: escribano.tomo ?? '',
    folio: escribano.folio ?? '',
  })
  const save = useMutation({
    mutationFn: () =>
      updateEscribano(escribano.id, {
        tomo: orNull(form.tomo),
        folio: orNull(form.folio),
        persona: {
          apellido: form.apellido.trim(),
          nombre: form.nombre.trim(),
          numero_documento: form.numero_documento.trim(),
          fecha_nacimiento: orNull(form.fecha_nacimiento),
          email: orNull(form.email),
          telefono: orNull(form.telefono),
          domicilio_real: orNull(form.domicilio_real),
        },
      }),
    onSuccess: async () => {
      await refresh()
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
      title="Editar datos"
      description="El CUIT y la matrícula no se editan: identifican al escribano. Cada cambio queda auditado."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Guardando…"
            onClick={() => {
              save.mutate()
            }}
          >
            Guardar cambios
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {problem && Object.keys(problem.fieldErrors).length === 0 && (
          <div className="sm:col-span-2">
            <Alert tone="danger">{problem.detail}</Alert>
          </div>
        )}
        <Field label="Apellido" {...bind('apellido')} />
        <Field label="Nombre" {...bind('nombre')} />
        <Field label="Número de documento" inputMode="numeric" {...bind('numero_documento')} />
        <Field label="Fecha de nacimiento" type="date" {...bind('fecha_nacimiento')} />
        <Field
          label="Correo electrónico"
          type="email"
          className="sm:col-span-2"
          {...bind('email')}
        />
        <Field label="Teléfono" type="tel" {...bind('telefono')} />
        <div className="grid grid-cols-2 gap-3">
          <Field label="Tomo" {...bind('tomo')} />
          <Field label="Folio" {...bind('folio')} />
        </div>
        <TextArea
          label="Domicilio real"
          rows={2}
          className="sm:col-span-2"
          {...bind('domicilio_real')}
        />
      </div>
    </Dialog>
  )
}

export function CuentaDialog({ escribano, open, onClose }: Props) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const save = useMutation({
    mutationFn: () => createCuenta(escribano.id, email.trim()),
    onSuccess: (data) => {
      queryClient.setQueryData(['escribano', escribano.id], data)
      setEmail('')
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
      title="Crear cuenta de autogestión"
      description="El escribano recibe un correo para definir su contraseña. Confirmá la dirección escribiéndola de nuevo."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            busy={save.isPending}
            busyLabel="Creando…"
            disabled={!email.trim()}
            onClick={() => {
              save.mutate()
            }}
          >
            Crear cuenta y enviar correo
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <p className="text-sm text-ink">
          Correo registrado en el padrón:{' '}
          <span className="font-semibold">{escribano.persona.email}</span>
        </p>
        <Field
          label="Confirmá el correo"
          type="email"
          autoComplete="off"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
          }}
          hint="Debe coincidir con el registrado."
        />
      </div>
    </Dialog>
  )
}
