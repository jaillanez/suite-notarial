import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CircleCheck, CircleDashed, Download, FilePlus2, FileX2, Upload } from 'lucide-react'
import { useState } from 'react'

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
import { MAX_BYTES, TIPOS_ACEPTADOS, formatTamano } from '../pagos/labels'
import {
  anularDocumento,
  cargarDocumento,
  descargarDocumento,
  type DocumentoPrestamo,
  type PrestamoDetalle,
  type TipoDocumento,
} from './api'
import { TIPO_DOCUMENTO } from './labels'

const TIPOS = new Set(TIPOS_ACEPTADOS.split(','))
const EXTENSION: Record<string, string> = {
  'application/pdf': 'pdf',
  'image/png': 'png',
  'image/jpeg': 'jpg',
}

function useActualizar(id: string) {
  const queryClient = useQueryClient()
  return (detalle: PrestamoDetalle) => {
    queryClient.setQueryData(['prestamo', id], detalle)
    void queryClient.invalidateQueries({ queryKey: ['prestamos'] })
  }
}

function CargarDocumento({
  p,
  open,
  onClose,
}: {
  p: PrestamoDetalle
  open: boolean
  onClose: () => void
}) {
  const actualizar = useActualizar(p.id)
  // Primero lo que falta de lo que exige la línea.
  const sugerido = p.documentacion_requerida.find((r) => !r.cargado)?.tipo ?? 'DOCUMENTO_IDENTIDAD'
  const [tipo, setTipo] = useState<TipoDocumento>(sugerido)
  const [descripcion, setDescripcion] = useState('')
  const [archivo, setArchivo] = useState<File | null>(null)
  // Lo que el navegador ya sabe del archivo; el servidor vuelve a validar por contenido.
  const errorArchivo =
    archivo && archivo.size > MAX_BYTES
      ? 'Supera los 10 MB.'
      : archivo && archivo.type && !TIPOS.has(archivo.type)
        ? 'Tiene que ser un PDF, PNG o JPG.'
        : undefined
  const cargar = useMutation({
    mutationFn: () =>
      cargarDocumento(p.id, { tipo, descripcion: descripcion.trim(), archivo: archivo as File }),
    onSuccess: (detalle) => {
      actualizar(detalle)
      cerrar()
    },
  })
  function cerrar() {
    cargar.reset()
    setArchivo(null)
    setDescripcion('')
    onClose()
  }
  const faltaDescripcion = tipo === 'OTRO' && !descripcion.trim()
  return (
    <Dialog
      open={open}
      onClose={cerrar}
      title={`Documentación de la solicitud N° ${String(p.numero)}`}
      description="El archivo queda en el expediente del préstamo. Si te equivocás, lo podés anular mientras la solicitud no esté resuelta."
      footer={
        <>
          <Button onClick={cerrar}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Upload}
            busy={cargar.isPending}
            busyLabel="Cargando…"
            disabled={!archivo || Boolean(errorArchivo) || faltaDescripcion}
            onClick={() => {
              cargar.mutate()
            }}
          >
            Cargar documento
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {cargar.isError && <Alert tone="danger">{toProblem(cargar.error).detail}</Alert>}
        <Select
          label="Documento"
          value={tipo}
          onChange={(e) => {
            setTipo(e.target.value as TipoDocumento)
          }}
          options={Object.entries(TIPO_DOCUMENTO).map(([value, label]) => ({ value, label }))}
        />
        <Field
          label={tipo === 'OTRO' ? 'Qué documento es' : 'Detalle (opcional)'}
          maxLength={200}
          hint={
            tipo === 'GARANTIA'
              ? 'Por ejemplo: escritura, tasación o informe de dominio.'
              : undefined
          }
          value={descripcion}
          onChange={(e) => {
            setDescripcion(e.target.value)
          }}
        />
        <FileField
          label="Archivo"
          accept={TIPOS_ACEPTADOS}
          formatos="PDF, PNG o JPG de hasta 10 MB"
          archivo={archivo}
          error={errorArchivo}
          onChange={setArchivo}
        />
      </div>
    </Dialog>
  )
}

function AnularDocumento({
  p,
  doc,
  onClose,
}: {
  p: PrestamoDetalle
  doc: DocumentoPrestamo | null
  onClose: () => void
}) {
  const actualizar = useActualizar(p.id)
  const [motivo, setMotivo] = useState('')
  const anular = useMutation({
    mutationFn: () => anularDocumento(p.id, doc?.id ?? '', motivo.trim()),
    onSuccess: (detalle) => {
      actualizar(detalle)
      cerrar()
    },
  })
  function cerrar() {
    anular.reset()
    setMotivo('')
    onClose()
  }
  return (
    <Dialog
      open={doc !== null}
      onClose={cerrar}
      title={doc ? `Anular ${TIPO_DOCUMENTO[doc.tipo].toLowerCase()}` : ''}
      description="No se borra: queda en el expediente marcado como anulado, con el motivo, y deja de contar como cargado."
      footer={
        <>
          <Button onClick={cerrar}>Cancelar</Button>
          <Button
            variant="danger"
            icon={FileX2}
            busy={anular.isPending}
            busyLabel="Anulando…"
            disabled={motivo.trim().length < 5}
            onClick={() => {
              anular.mutate()
            }}
          >
            Anular documento
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {anular.isError && <Alert tone="danger">{toProblem(anular.error).detail}</Alert>}
        <TextArea
          label="Motivo"
          hint="Obligatorio, al menos 5 caracteres. Por ejemplo: archivo equivocado."
          value={motivo}
          onChange={(e) => {
            setMotivo(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

function FilaDocumento({
  p,
  doc,
  onAnular,
}: {
  p: PrestamoDetalle
  doc: DocumentoPrestamo
  onAnular: () => void
}) {
  const descarga = useMutation({
    mutationFn: () =>
      descargarDocumento(
        p.id,
        doc,
        `prestamo-${String(p.numero)}-${doc.tipo.toLowerCase().replaceAll('_', '-')}.${EXTENSION[doc.mime_type] ?? 'pdf'}`,
      ),
  })
  const anulado = doc.anulado_en !== null
  return (
    <li className="flex flex-col gap-3 px-5 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <div className={`min-w-0 text-sm ${anulado ? 'text-ink-muted' : ''}`}>
        <p className={`font-semibold ${anulado ? 'line-through' : 'text-ink'}`}>
          {TIPO_DOCUMENTO[doc.tipo]}
          {doc.descripcion && <span className="font-normal"> · {doc.descripcion}</span>}
        </p>
        <p className="truncate text-ink-muted tabular-nums">
          {doc.nombre_original} · {formatTamano(doc.tamano_bytes)} · {doc.subido_por},{' '}
          {formatLocalDateTime(new Date(doc.created_at))}
        </p>
        {anulado && (
          <p className="mt-0.5 text-danger-700">
            Anulado{doc.motivo_anulacion && `: ${doc.motivo_anulacion}`}
          </p>
        )}
        {descarga.isError && (
          <p className="mt-0.5 font-medium text-danger-700">{toProblem(descarga.error).detail}</p>
        )}
      </div>
      <div className="flex shrink-0 gap-2">
        <Button
          variant="ghost"
          icon={Download}
          busy={descarga.isPending}
          busyLabel="Descargando…"
          onClick={() => {
            descarga.mutate()
          }}
        >
          Descargar
        </Button>
        {doc.puede_anular && (
          <Button variant="ghost" icon={FileX2} onClick={onAnular}>
            Anular
          </Button>
        )}
      </div>
    </li>
  )
}

/** Documentación de la solicitud: lo que exige la línea y los archivos cargados. */
export function Documentacion({ p }: { p: PrestamoDetalle }) {
  const [cargando, setCargando] = useState(false)
  const [anulando, setAnulando] = useState<DocumentoPrestamo | null>(null)
  const faltan = p.documentacion_requerida.filter((r) => !r.cargado).length
  return (
    <Panel
      title="Documentación"
      description={
        p.documentacion_requerida.length === 0
          ? 'La línea no exige documentación para otorgar. Podés agregar la que haga falta.'
          : faltan > 0 && p.estado === 'SOLICITADO'
            ? 'La línea exige estos documentos: sin ellos la solicitud no se puede otorgar.'
            : 'La línea exige estos documentos.'
      }
      actions={
        p.puede_cargar_documentos && (
          <Button
            icon={FilePlus2}
            onClick={() => {
              setCargando(true)
            }}
          >
            Agregar documento
          </Button>
        )
      }
    >
      {p.documentacion_requerida.length > 0 && (
        <ul className="flex flex-wrap gap-x-6 gap-y-2 border-b border-line px-5 py-3.5 text-sm sm:px-6">
          {p.documentacion_requerida.map((r) => (
            <li key={r.tipo} className="flex items-center gap-2">
              {r.cargado ? (
                <CircleCheck
                  aria-hidden="true"
                  className="size-4 text-success-700"
                  strokeWidth={2.25}
                />
              ) : (
                <CircleDashed
                  aria-hidden="true"
                  className="size-4 text-danger-700"
                  strokeWidth={2.25}
                />
              )}
              <span className={r.cargado ? 'text-ink' : 'font-semibold text-danger-700'}>
                {TIPO_DOCUMENTO[r.tipo]}
                <span className="sr-only">{r.cargado ? ': cargado' : ': falta'}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {p.documentos.length === 0 ? (
        <p className="px-5 py-6 text-sm text-ink-muted sm:px-6">
          Todavía no hay documentos cargados.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {p.documentos.map((d) => (
            <FilaDocumento
              key={d.id}
              p={p}
              doc={d}
              onAnular={() => {
                setAnulando(d)
              }}
            />
          ))}
        </ul>
      )}
      {p.puede_cargar_documentos && (
        <CargarDocumento
          p={p}
          open={cargando}
          onClose={() => {
            setCargando(false)
          }}
        />
      )}
      <AnularDocumento
        p={p}
        doc={anulando}
        onClose={() => {
          setAnulando(null)
        }}
      />
    </Panel>
  )
}
