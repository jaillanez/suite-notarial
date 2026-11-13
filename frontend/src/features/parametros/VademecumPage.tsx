import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, Pencil, Plus, Save, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { useSession } from '../auth/session'
import {
  aprobarVademecum,
  fetchVademecum,
  fetchVademecumPendientes,
  proponerVademecum,
  rechazarVademecum,
  type CategoriaActo,
  type MotivoExencion,
  type VademecumActo,
} from '../ddjj/api'
import { CATEGORIA, MOTIVO_EXENCION } from '../ddjj/labels'
import { normalizar } from '../ddjj/vademecum'
import { formatDate, todayIso } from '../padron/labels'

/** Categorías del vademécum, en el orden del documento de la Caja. */
const GRUPOS: { categoria: CategoriaActo; titulo: string }[] = [
  { categoria: 'ESCRITURA_CON_VALOR', titulo: 'I · Aporte variable' },
  { categoria: 'OTRO_ACTO', titulo: 'II · Aportes fijos mayores' },
  { categoria: 'ACTA_O_PODER', titulo: 'III · Aportes fijos menores' },
  { categoria: 'EXENTO', titulo: 'IV · Actos exentos o que no generan aporte' },
]
const MOTIVOS: MotivoExencion[] = [
  'ACTA_SUBSANATORIA',
  'CONVENIO_IPV',
  'ASOCIACION_INTERMEDIA_IPV',
  'REGULACION_DOMINIAL',
]

/** Código a partir del nombre: «Cesión de cuotas» → CESION_DE_CUOTAS. */
function codigoDe(nombre: string): string {
  return normalizar(nombre)
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/^(\d)/, 'A_$1')
    .slice(0, 60)
}

function primeroDelMesQueViene(): string {
  const [anio = 0, mes = 1] = todayIso().split('-').map(Number)
  const siguiente =
    mes === 12 ? `${String(anio + 1)}-01` : `${String(anio)}-${String(mes + 1).padStart(2, '0')}`
  return `${siguiente}-01`
}

function VersionDialog({
  base,
  abierto,
  onClose,
}: {
  /** Versión que se reemplaza; sin ella, se agrega un acto nuevo. */
  base: VademecumActo | null
  abierto: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<{
    nombre: string
    categoria: CategoriaActo
    motivo_exencion: MotivoExencion | ''
    aclaracion: string
    sinonimos: string
    fecha_desde: string
    resolucion: string
    motivo: string
  }>({
    nombre: base?.nombre ?? '',
    categoria: base?.categoria ?? 'OTRO_ACTO',
    motivo_exencion: base?.motivo_exencion ?? '',
    aclaracion: base?.aclaracion ?? '',
    sinonimos: base?.sinonimos ?? '',
    fecha_desde: primeroDelMesQueViene(),
    resolucion: '',
    motivo: '',
  })
  const exento = form.categoria === 'EXENTO'
  const codigo = base?.codigo ?? codigoDe(form.nombre)
  const save = useMutation({
    mutationFn: () =>
      proponerVademecum({
        codigo,
        nombre: form.nombre.trim(),
        categoria: form.categoria,
        motivo_exencion: exento && form.motivo_exencion ? form.motivo_exencion : null,
        aclaracion: form.aclaracion.trim() || null,
        sinonimos: form.sinonimos.trim() || null,
        // Un acto nuevo va al final de su grupo.
        orden: base?.orden ?? 9_000,
        fecha_desde: form.fecha_desde,
        resolucion: form.resolucion.trim(),
        motivo: form.motivo.trim(),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ddjj', 'vademecum'] })
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const bind = (
    key: 'nombre' | 'aclaracion' | 'sinonimos' | 'fecha_desde' | 'resolucion' | 'motivo',
  ) => ({
    value: form[key],
    onChange: (e: { target: { value: string } }) => {
      setForm((f) => ({ ...f, [key]: e.target.value }))
    },
    error: problem?.fieldErrors[key],
  })
  const listo =
    form.nombre.trim().length >= 3 &&
    codigo.length >= 3 &&
    (!exento || form.motivo_exencion !== '') &&
    form.fecha_desde !== '' &&
    form.resolucion.trim().length >= 3 &&
    form.motivo.trim().length >= 5

  return (
    <Dialog
      open={abierto}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={base ? `Cambiar «${base.nombre}»` : 'Proponer un acto nuevo'}
      description={
        base
          ? 'Queda pendiente hasta que la apruebe otra persona. Aprobada, rige desde la fecha indicada (mañana o después) y la versión actual deja de regir el día anterior. Los actos ya declarados conservan cómo se valorizaron.'
          : 'Queda pendiente hasta que la apruebe otra persona. El monto sale de los parámetros de su categoría.'
      }
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Save}
            busy={save.isPending}
            busyLabel="Guardando…"
            disabled={!listo}
            onClick={() => {
              save.mutate()
            }}
          >
            {base ? 'Proponer versión nueva' : 'Proponer acto'}
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
        <Field
          className="sm:col-span-2"
          label="Nombre del acto"
          maxLength={200}
          hint={base ? undefined : codigo ? `Código: ${codigo}` : undefined}
          {...bind('nombre')}
        />
        <div className={exento ? '' : 'sm:col-span-2'}>
          <Select
            label="Cómo aporta"
            value={form.categoria}
            onChange={(e) => {
              setForm((f) => ({ ...f, categoria: e.target.value as CategoriaActo }))
            }}
            options={GRUPOS.map((g) => ({
              value: g.categoria,
              label: CATEGORIA[g.categoria].label,
            }))}
          />
        </div>
        {exento && (
          <Select
            label="Exención"
            value={form.motivo_exencion}
            onChange={(e) => {
              setForm((f) => ({ ...f, motivo_exencion: e.target.value as MotivoExencion | '' }))
            }}
            options={[
              ...(form.motivo_exencion ? [] : [{ value: '', label: 'Elegí la exención' }]),
              ...MOTIVOS.map((m) => ({ value: m, label: MOTIVO_EXENCION[m] })),
            ]}
          />
        )}
        <TextArea
          className="sm:col-span-2"
          label="Aclaración (opcional)"
          rows={2}
          hint="Lo que el escribano tiene que leer antes de elegirlo, p. ej. «Excepto las del IPV»."
          {...bind('aclaracion')}
        />
        <Field
          className="sm:col-span-2"
          label="Sinónimos (opcional)"
          maxLength={500}
          hint="Otras formas de nombrarlo, separadas por coma: el buscador los encuentra."
          {...bind('sinonimos')}
        />
        <Field
          label="Rige desde"
          type="date"
          className="[&_input]:tabular-nums"
          {...bind('fecha_desde')}
        />
        <Field label="Resolución o asamblea" maxLength={150} {...bind('resolucion')} />
        <TextArea
          className="sm:col-span-2"
          label="Motivo"
          rows={2}
          hint="Obligatorio. Queda registrado en la auditoría."
          {...bind('motivo')}
        />
      </div>
    </Dialog>
  )
}

function RechazoDialog({ acto, onClose }: { acto: VademecumActo | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [motivo, setMotivo] = useState('')
  const save = useMutation({
    mutationFn: () => rechazarVademecum(acto?.id ?? '', motivo.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ddjj', 'vademecum'] })
      onClose()
    },
  })
  return (
    <Dialog
      open={acto !== null}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title={acto ? `Rechazar la propuesta «${acto.nombre}»` : 'Rechazar la propuesta'}
      description="La propuesta no rige y queda en el historial con el motivo."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="danger"
            busy={save.isPending}
            busyLabel="Rechazando…"
            disabled={motivo.trim().length < 5}
            onClick={() => {
              save.mutate()
            }}
          >
            Rechazar
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <TextArea
          label="Motivo"
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
          hint="Obligatorio. Queda registrado en la auditoría."
        />
      </div>
    </Dialog>
  )
}

/** Propuestas que esperan la aprobación de otra persona: quien propuso no puede aprobarlas. */
function Pendientes({ onRechazar }: { onRechazar: (acto: VademecumActo) => void }) {
  const { user, can } = useSession()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['ddjj', 'vademecum', 'pendientes'],
    queryFn: fetchVademecumPendientes,
  })
  const pendientes = query.data ?? []
  const aprobables = pendientes.filter((p) => p.created_by_user_id !== user?.id)
  const puedeAprobar = can('parameters:approve')
  const aprobar = useMutation({
    mutationFn: aprobarVademecum,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ddjj', 'vademecum'] })
    },
  })
  if (pendientes.length === 0) return null
  return (
    <Panel
      className="mb-6"
      title="Propuestas pendientes de aprobación"
      description="No rigen hasta que las apruebe una persona distinta de quien las propuso."
      actions={
        puedeAprobar && aprobables.length > 1 ? (
          <Button
            icon={Check}
            busy={aprobar.isPending}
            busyLabel="Aprobando…"
            onClick={() => {
              aprobar.mutate(aprobables.map((p) => p.id))
            }}
          >
            Aprobar las {aprobables.length}
          </Button>
        ) : undefined
      }
    >
      {aprobar.isError && (
        <div className="px-5 pt-4 sm:px-6">
          <Alert tone="danger">{toProblem(aprobar.error).detail}</Alert>
        </div>
      )}
      <ul className="divide-y divide-line">
        {pendientes.map((p) => {
          const propia = p.created_by_user_id === user?.id
          return (
            <li
              key={p.id}
              className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2 px-5 py-3 sm:flex-nowrap sm:px-6"
            >
              <span className="min-w-0">
                <span className="block font-medium text-ink">{p.nombre}</span>
                <span className="block text-sm text-ink-muted">
                  {CATEGORIA[p.categoria].label}
                  {p.motivo_exencion && ` · ${MOTIVO_EXENCION[p.motivo_exencion]}`}
                </span>
                <span className="block text-xs text-ink-muted tabular-nums">
                  {p.version > 1 ? `Versión ${String(p.version)}` : 'Acto nuevo'} · desde el{' '}
                  {formatDate(p.fecha_desde)} · {p.resolucion}
                </span>
              </span>
              <span className="flex shrink-0 flex-wrap items-center gap-2">
                {propia || !puedeAprobar ? (
                  <StatusIndicator
                    tone="warning"
                    label={propia ? 'La aprueba otra persona' : 'Pendiente'}
                  />
                ) : (
                  <>
                    <Button
                      variant="ghost"
                      icon={Check}
                      aria-label={`Aprobar ${p.nombre}`}
                      disabled={aprobar.isPending}
                      onClick={() => {
                        aprobar.mutate([p.id])
                      }}
                    >
                      Aprobar
                    </Button>
                    <Button
                      variant="ghost"
                      icon={X}
                      aria-label={`Rechazar ${p.nombre}`}
                      onClick={() => {
                        onRechazar(p)
                      }}
                    >
                      Rechazar
                    </Button>
                  </>
                )}
              </span>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}

/** Vademécum de aportes vigente a una fecha, por categoría, con su administración. */
export function VademecumPage() {
  const { can } = useSession()
  const editable = can('parameters:write')
  const [fecha, setFecha] = useState(todayIso())
  const [version, setVersion] = useState<{ abierto: boolean; base: VademecumActo | null }>({
    abierto: false,
    base: null,
  })
  const [rechazando, setRechazando] = useState<VademecumActo | null>(null)
  const query = useQuery({
    queryKey: ['ddjj', 'vademecum', fecha],
    queryFn: () => fetchVademecum(fecha),
    enabled: /^\d{4}-\d{2}-\d{2}$/.test(fecha),
  })
  const actos = query.data ?? []
  const resolucion = actos[0]?.resolucion

  return (
    <>
      <Link
        to="/parametros"
        className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-medium"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Parámetros
      </Link>
      <PageHeader
        title="Vademécum de aportes"
        description="Qué aporta cada acto. El escribano elige el acto al cargar la DDJJ y el sistema aplica su categoría; los montos salen de los parámetros vigentes. Cada cambio es una versión nueva que aprueba otra persona y queda en la auditoría."
      />
      {can('parameters:read') && <Pendientes onRechazar={setRechazando} />}
      <Panel
        title={resolucion ? `Vigente al ${formatDate(fecha)}` : 'Actos'}
        description={resolucion}
        actions={
          editable ? (
            <Button
              variant="primary"
              icon={Plus}
              onClick={() => {
                setVersion({ abierto: true, base: null })
              }}
            >
              Proponer acto
            </Button>
          ) : undefined
        }
      >
        <div className="border-b border-line px-5 py-4 sm:px-6">
          <Field
            label="Vigente al"
            type="date"
            value={fecha}
            onChange={(e) => {
              setFecha(e.target.value)
            }}
            className="max-w-56 [&_input]:tabular-nums"
          />
        </div>
        {query.isError && (
          <div className="px-5 py-4 sm:px-6">
            <Alert tone="danger">{toProblem(query.error).detail}</Alert>
          </div>
        )}
        <div aria-busy={query.isFetching}>
          {query.isPending && (
            <div className="grid gap-3 px-5 py-4 sm:px-6">
              {Array.from({ length: 4 }, (_, i) => (
                <span key={i} className="block h-10 animate-pulse rounded-control bg-brand-50" />
              ))}
            </div>
          )}
          {query.isSuccess && actos.length === 0 && (
            <p className="px-5 py-10 text-center text-ink-muted sm:px-6">
              No hay vademécum vigente a esa fecha: los actos se cargan eligiendo el tipo de aporte.
            </p>
          )}
          {GRUPOS.map((g) => {
            const delGrupo = actos.filter((a) => a.categoria === g.categoria)
            if (delGrupo.length === 0) return null
            return (
              <section key={g.categoria} aria-labelledby={`grupo-${g.categoria}`}>
                <h3
                  id={`grupo-${g.categoria}`}
                  className="border-y border-line bg-surface-sunken px-5 py-2 text-xs font-semibold text-ink-muted sm:px-6"
                >
                  {g.titulo}
                </h3>
                <ul className="divide-y divide-line">
                  {delGrupo.map((a) => (
                    <li
                      key={a.id}
                      className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2 px-5 py-3 sm:flex-nowrap sm:px-6"
                    >
                      <span className="min-w-0">
                        <span className="block font-medium text-ink">{a.nombre}</span>
                        {a.motivo_exencion && (
                          <span className="block text-sm text-ink-muted">
                            {MOTIVO_EXENCION[a.motivo_exencion]}
                          </span>
                        )}
                        {a.aclaracion && (
                          <span className="block max-w-[65ch] text-sm text-ink-muted">
                            {a.aclaracion}
                          </span>
                        )}
                        <span className="block text-xs text-ink-muted tabular-nums">
                          Versión {a.version} · desde el {formatDate(a.fecha_desde)}
                          {a.fecha_hasta && ` hasta el ${formatDate(a.fecha_hasta)}`}
                        </span>
                      </span>
                      {editable && (
                        <span className="-mr-2 flex shrink-0 gap-1">
                          <Button
                            variant="ghost"
                            icon={Pencil}
                            aria-label={`Cambiar ${a.nombre}`}
                            onClick={() => {
                              setVersion({ abierto: true, base: a })
                            }}
                          >
                            Cambiar
                          </Button>
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )
          })}
        </div>
      </Panel>
      <VersionDialog
        key={`${String(version.abierto)}-${version.base?.id ?? 'nuevo'}`}
        base={version.base}
        abierto={version.abierto}
        onClose={() => {
          setVersion({ abierto: false, base: null })
        }}
      />
      <RechazoDialog
        key={rechazando?.id ?? 'ninguno'}
        acto={rechazando}
        onClose={() => {
          setRechazando(null)
        }}
      />
    </>
  )
}
