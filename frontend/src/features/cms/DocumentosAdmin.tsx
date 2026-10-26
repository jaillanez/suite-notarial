import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ChevronDown, CircleCheck, CircleX, FilePlus2, FileUp, Send } from 'lucide-react'
import { useState } from 'react'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { FileField } from '../../components/ui/FileField'
import { Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { formatLocalDateTime } from '../../lib/datetime'
import { formatTamano } from '../pagos/labels'
import {
  crearDocumento,
  estadoDocumento,
  fetchDocumento,
  fetchDocumentos,
  nuevaVersion,
  type Documento,
  type EstadoPublicacion,
  type TipoDocumento,
} from './api'
import { ESTADO_PUBLICACION, TIPO_DOCUMENTO, rutaLocal } from './labels'

const MAX_MB = 25

function errorPdf(archivo: File | null): string | undefined {
  if (!archivo) return undefined
  if (archivo.size > MAX_MB * 1024 * 1024) return `Supera los ${String(MAX_MB)} MB.`
  if (archivo.type && archivo.type !== 'application/pdf') return 'Tiene que ser un PDF.'
  return undefined
}

function useInvalidar() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['cms', 'documentos'] })
}

function NuevoDocumentoDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const invalidar = useInvalidar()
  const [archivo, setArchivo] = useState<File | null>(null)
  const [form, setForm] = useState({
    tipo: 'ESTADO_CONTABLE' as TipoDocumento,
    ejercicio: String(new Date().getFullYear() - 1),
    titulo: '',
    descripcion: '',
  })
  const save = useMutation({
    mutationFn: () =>
      crearDocumento({
        ...form,
        titulo: form.titulo.trim(),
        descripcion: form.descripcion.trim(),
        archivo: archivo as File,
      }),
    onSuccess: async () => {
      await invalidar()
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const errorArchivo = errorPdf(archivo)
  return (
    <Dialog
      open={open}
      onClose={() => {
        save.reset()
        onClose()
      }}
      title="Nuevo documento oficial"
      description="Se valida que sea un PDF íntegro y se guarda su huella. Queda como borrador hasta que lo publiques."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={FileUp}
            busy={save.isPending}
            busyLabel="Validando y subiendo…"
            disabled={!archivo || Boolean(errorArchivo) || form.titulo.trim().length < 3}
            onClick={() => {
              save.mutate()
            }}
          >
            Subir documento
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {problem && (
          <div className="sm:col-span-2">
            <Alert tone="danger">{problem.detail}</Alert>
          </div>
        )}
        <Select
          label="Tipo"
          value={form.tipo}
          onChange={(e) => {
            setForm((f) => ({ ...f, tipo: e.target.value as TipoDocumento }))
          }}
          options={(Object.keys(TIPO_DOCUMENTO) as TipoDocumento[]).map((t) => ({
            value: t,
            label: TIPO_DOCUMENTO[t],
          }))}
        />
        <Field
          label="Ejercicio"
          inputMode="numeric"
          className="[&_input]:tabular-nums"
          value={form.ejercicio}
          onChange={(e) => {
            setForm((f) => ({ ...f, ejercicio: e.target.value }))
          }}
        />
        <Field
          className="sm:col-span-2"
          label="Título"
          placeholder="Estados contables al 31 de diciembre"
          maxLength={200}
          value={form.titulo}
          onChange={(e) => {
            setForm((f) => ({ ...f, titulo: e.target.value }))
          }}
        />
        <TextArea
          className="sm:col-span-2"
          label="Descripción (opcional)"
          maxLength={2000}
          value={form.descripcion}
          onChange={(e) => {
            setForm((f) => ({ ...f, descripcion: e.target.value }))
          }}
        />
        <div className="sm:col-span-2">
          <FileField
            label="Archivo"
            accept="application/pdf"
            formatos={`PDF de hasta ${String(MAX_MB)} MB, sin contraseña ni contenido activo`}
            archivo={archivo}
            error={errorArchivo}
            onChange={setArchivo}
          />
        </div>
      </div>
    </Dialog>
  )
}

function ReemplazarDialog({ doc, onClose }: { doc: Documento | null; onClose: () => void }) {
  const invalidar = useInvalidar()
  const [archivo, setArchivo] = useState<File | null>(null)
  const [motivo, setMotivo] = useState('')
  const save = useMutation({
    mutationFn: () => nuevaVersion(doc?.id ?? '', motivo.trim(), archivo as File),
    onSuccess: async () => {
      await invalidar()
      onClose()
    },
  })
  const errorArchivo = errorPdf(archivo)
  return (
    <Dialog
      open={doc !== null}
      onClose={onClose}
      title="Reemplazar el archivo"
      description="El enlace no cambia: pasa a servir la versión nueva y la anterior queda en el historial, accesible y verificable."
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={FileUp}
            busy={save.isPending}
            busyLabel="Validando y subiendo…"
            disabled={!archivo || Boolean(errorArchivo) || motivo.trim().length < 5}
            onClick={() => {
              save.mutate()
            }}
          >
            Subir versión nueva
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {save.isError && <Alert tone="danger">{toProblem(save.error).detail}</Alert>}
        <FileField
          label="Archivo nuevo"
          accept="application/pdf"
          formatos={`PDF de hasta ${String(MAX_MB)} MB`}
          archivo={archivo}
          error={errorArchivo}
          onChange={setArchivo}
        />
        <TextArea
          label="Motivo del reemplazo"
          hint="Obligatorio y público: figura en el historial del documento."
          maxLength={1000}
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

function Versiones({ id }: { id: string }) {
  const query = useQuery({
    queryKey: ['cms', 'documentos', id, 'versiones'],
    queryFn: () => fetchDocumento(id),
  })
  if (query.isPending) {
    return <span className="block h-16 animate-pulse rounded-control bg-brand-50" />
  }
  if (query.isError) return <Alert tone="danger">{toProblem(query.error).detail}</Alert>
  return (
    <ul className="divide-y divide-line rounded-control border border-line bg-surface">
      {query.data.versiones.map((v) => (
        <li
          key={v.version}
          className="grid gap-1 px-4 py-3 text-sm sm:grid-cols-[1fr_auto] sm:gap-4"
        >
          <div className="min-w-0">
            <p className="font-semibold text-ink tabular-nums">
              <a href={rutaLocal(v.url)} target="_blank" rel="noopener">
                Versión {v.version}
              </a>
              <span className="font-normal text-ink-muted">
                {' '}
                · {v.paginas} pág. · {formatTamano(v.tamano_bytes)} ·{' '}
                {formatLocalDateTime(new Date(v.created_at))}
              </span>
            </p>
            <p className="text-ink-muted">
              {v.nombre_original}
              {v.subido_por && ` · ${v.subido_por}`}
              {v.motivo && ` · ${v.motivo}`}
            </p>
            <code className="block font-mono text-xs break-all text-ink-muted">{v.sha256}</code>
          </div>
          {v.integra === false ? (
            <span className="flex items-center gap-1.5 self-start font-semibold text-danger-700">
              <CircleX aria-hidden="true" className="size-4" strokeWidth={2.25} />
              Archivo alterado
            </span>
          ) : (
            <span className="flex items-center gap-1.5 self-start text-success-700">
              <CircleCheck aria-hidden="true" className="size-4" strokeWidth={2.25} />
              Íntegro
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

export function DocumentosAdmin() {
  const invalidar = useInvalidar()
  const query = useQuery({ queryKey: ['cms', 'documentos'], queryFn: fetchDocumentos })
  const [creando, setCreando] = useState(false)
  const [reemplazando, setReemplazando] = useState<Documento | null>(null)
  const [abierto, setAbierto] = useState<string | null>(null)
  const estado = useMutation({
    mutationFn: ({ id, nuevo }: { id: string; nuevo: EstadoPublicacion }) =>
      estadoDocumento(id, nuevo),
    onSuccess: invalidar,
  })

  return (
    <Panel
      title="Documentos oficiales"
      description="Estados contables, memorias y resoluciones. Cada uno tiene un enlace permanente; reemplazar el archivo crea una versión nueva."
      actions={
        <Button
          variant="primary"
          icon={FilePlus2}
          onClick={() => {
            setCreando(true)
          }}
        >
          Nuevo documento
        </Button>
      }
    >
      {(query.isError || estado.isError) && (
        <div className="px-5 py-4 sm:px-6">
          <Alert tone="danger">{toProblem(query.error ?? estado.error).detail}</Alert>
        </div>
      )}
      <ul className="divide-y divide-line">
        {query.data?.length === 0 && (
          <li className="px-5 py-10 text-center text-ink-muted sm:px-6">
            Todavía no hay documentos. Subí el primero con «Nuevo documento».
          </li>
        )}
        {query.data?.map((d) => {
          const e = ESTADO_PUBLICACION[d.estado]
          const vigente = d.versiones[0]
          return (
            <li key={d.id} className="px-5 py-4 sm:px-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 items-baseline gap-4">
                  <span className="text-xl font-semibold text-brand-900 tabular-nums">
                    {d.ejercicio}
                  </span>
                  <span className="min-w-0">
                    <span className="block font-semibold text-ink">{d.titulo}</span>
                    <span className="block text-sm text-ink-muted tabular-nums">
                      {TIPO_DOCUMENTO[d.tipo]}
                      {vigente &&
                        ` · Versión ${String(vigente.version)} · ${String(vigente.paginas)} pág.`}
                    </span>
                    <a
                      href={rutaLocal(d.url)}
                      target="_blank"
                      rel="noopener"
                      className="text-sm break-all"
                    >
                      {d.url}
                    </a>
                  </span>
                </div>
                <StatusIndicator tone={e.tone} label={e.label} />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  variant="ghost"
                  icon={ChevronDown}
                  aria-expanded={abierto === d.id}
                  className="-ml-4"
                  onClick={() => {
                    setAbierto((a) => (a === d.id ? null : d.id))
                  }}
                >
                  Versiones e integridad
                </Button>
                <Button
                  variant="ghost"
                  icon={FileUp}
                  onClick={() => {
                    setReemplazando(d)
                  }}
                >
                  Reemplazar archivo
                </Button>
                {d.estado === 'PUBLICADO' ? (
                  <Button
                    variant="ghost"
                    icon={Archive}
                    onClick={() => {
                      estado.mutate({ id: d.id, nuevo: 'ARCHIVADO' })
                    }}
                  >
                    Archivar
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    icon={Send}
                    onClick={() => {
                      estado.mutate({ id: d.id, nuevo: 'PUBLICADO' })
                    }}
                  >
                    {d.estado === 'ARCHIVADO' ? 'Volver a publicar' : 'Publicar'}
                  </Button>
                )}
              </div>
              {abierto === d.id && (
                <div className="mt-3">
                  <Versiones id={d.id} />
                </div>
              )}
            </li>
          )
        })}
      </ul>
      <NuevoDocumentoDialog
        key={`nuevo-${String(creando)}`}
        open={creando}
        onClose={() => {
          setCreando(false)
        }}
      />
      <ReemplazarDialog
        key={reemplazando?.id ?? 'ninguno'}
        doc={reemplazando}
        onClose={() => {
          setReemplazando(null)
        }}
      />
    </Panel>
  )
}
