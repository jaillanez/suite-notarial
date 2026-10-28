import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ImageMinus, ImagePlus, Pencil, Plus, Send } from 'lucide-react'
import { useState } from 'react'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { FileField } from '../../components/ui/FileField'
import { Pagination } from '../../components/ui/Pagination'
import { Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import {
  actualizarNovedad,
  crearNovedad,
  estadoNovedad,
  fetchNovedades,
  quitarImagen,
  subirImagen,
  type EstadoPublicacion,
  type Novedad,
  type SeccionNovedad,
} from './api'
import { ESTADO_PUBLICACION, SECCION_NOVEDAD, fechaLarga } from './labels'

function NovedadDialog({
  novedad,
  open,
  onClose,
}: {
  novedad?: Novedad
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    titulo: novedad?.titulo ?? '',
    resumen: novedad?.resumen ?? '',
    seccion: novedad?.seccion ?? 'NOVEDADES',
    contenido: novedad?.contenido ?? '',
    slug: novedad?.slug ?? '',
  })
  const publicada = novedad !== undefined && novedad.estado !== 'BORRADOR'
  const save = useMutation({
    mutationFn: () => {
      const data = {
        titulo: form.titulo.trim(),
        resumen: form.resumen.trim() || null,
        seccion: form.seccion,
        contenido: form.contenido.trim(),
        slug: form.slug.trim() || null,
      }
      return novedad ? actualizarNovedad(novedad.id, data) : crearNovedad(data)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['cms', 'novedades'] })
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const bind = (key: 'titulo' | 'resumen' | 'contenido' | 'slug') => ({
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
      title={novedad ? 'Editar novedad' : 'Nueva novedad'}
      description={
        publicada
          ? 'Está publicada: los cambios se ven en el sitio apenas guardes.'
          : 'Se guarda como borrador; se ve en el sitio cuando la publicás.'
      }
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            busy={save.isPending}
            busyLabel="Guardando…"
            disabled={form.titulo.trim().length < 3 || form.contenido.trim().length < 10}
            onClick={() => {
              save.mutate()
            }}
          >
            Guardar
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {problem && <Alert tone="danger">{problem.detail}</Alert>}
        <Field label="Título" maxLength={200} {...bind('titulo')} />
        <Select
          label="Sección"
          value={form.seccion}
          onChange={(e) => {
            setForm((f) => ({ ...f, seccion: e.target.value as SeccionNovedad }))
          }}
          options={Object.entries(SECCION_NOVEDAD).map(([value, label]) => ({ value, label }))}
        />
        <Field
          label="Resumen (opcional)"
          maxLength={400}
          hint="Una o dos oraciones para la portada."
          {...bind('resumen')}
        />
        <TextArea
          label="Contenido"
          rows={10}
          hint="Texto sin formato. Separá los párrafos con una línea en blanco."
          {...bind('contenido')}
        />
        <Field
          label="Enlace"
          placeholder="se-arma-con-el-titulo"
          disabled={publicada}
          hint={
            publicada
              ? 'El enlace de una novedad publicada no cambia.'
              : 'Opcional: minúsculas, números y guiones. Vacío, se arma con el título.'
          }
          {...bind('slug')}
        />
      </div>
    </Dialog>
  )
}

const MAX_IMAGEN_MB = 5

function ImagenDialog({ novedad, onClose }: { novedad: Novedad | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [archivo, setArchivo] = useState<File | null>(null)
  const [alt, setAlt] = useState(novedad?.imagen_alt ?? '')
  const grande = archivo !== null && archivo.size > MAX_IMAGEN_MB * 1024 * 1024
  const cerrar = () => {
    setArchivo(null)
    onClose()
  }
  const listo = async () => {
    await queryClient.invalidateQueries({ queryKey: ['cms', 'novedades'] })
    await queryClient.invalidateQueries({ queryKey: ['sitio'] })
    cerrar()
  }
  const subir = useMutation({
    mutationFn: () => {
      if (!novedad || !archivo) throw new Error('Elegí una imagen.')
      return subirImagen(novedad.id, archivo, alt.trim())
    },
    onSuccess: listo,
  })
  const quitar = useMutation({
    mutationFn: () => {
      if (!novedad) throw new Error('Sin nota.')
      return quitarImagen(novedad.id)
    },
    onSuccess: listo,
  })
  const problem = subir.isError
    ? toProblem(subir.error)
    : quitar.isError
      ? toProblem(quitar.error)
      : null

  return (
    <Dialog
      open={novedad !== null}
      onClose={cerrar}
      title="Imagen de la nota"
      description={novedad?.titulo}
      footer={
        <>
          {novedad?.imagen_url && (
            <Button
              variant="danger"
              icon={ImageMinus}
              busy={quitar.isPending}
              busyLabel="Quitando…"
              onClick={() => {
                quitar.mutate()
              }}
            >
              Quitar imagen
            </Button>
          )}
          <Button onClick={cerrar}>Cancelar</Button>
          <Button
            variant="primary"
            busy={subir.isPending}
            busyLabel="Subiendo…"
            disabled={!archivo || grande || alt.trim().length < 3}
            onClick={() => {
              subir.mutate()
            }}
          >
            {novedad?.imagen_url ? 'Reemplazar imagen' : 'Guardar imagen'}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {problem && <Alert tone="danger">{problem.detail}</Alert>}
        {novedad?.imagen_url && !archivo && (
          <img
            src={novedad.imagen_url}
            alt={novedad.imagen_alt ?? ''}
            className="aspect-[16/9] w-full rounded-panel border border-line object-cover"
          />
        )}
        <FileField
          label={novedad?.imagen_url ? 'Imagen nueva' : 'Imagen'}
          accept="image/jpeg,image/png,image/webp"
          formatos={`JPG, PNG o WEBP, hasta ${String(MAX_IMAGEN_MB)} MB. Ideal: horizontal, 1600 × 900.`}
          archivo={archivo}
          error={grande ? `La imagen supera los ${String(MAX_IMAGEN_MB)} MB.` : undefined}
          onChange={setArchivo}
        />
        <Field
          label="Qué muestra la imagen"
          value={alt}
          maxLength={200}
          hint="Para quien no puede verla (lector de pantalla). También se usa como epígrafe."
          onChange={(e) => {
            setAlt(e.target.value)
          }}
        />
      </div>
    </Dialog>
  )
}

export function NovedadesAdmin() {
  const queryClient = useQueryClient()
  const [filtro, setFiltro] = useState({ page: 1, estado: '' as EstadoPublicacion | '' })
  const query = useQuery({
    queryKey: ['cms', 'novedades', filtro],
    queryFn: () => fetchNovedades({ ...filtro, pageSize: 20 }),
    placeholderData: keepPreviousData,
  })
  const [editando, setEditando] = useState<{ open: boolean; item?: Novedad }>({ open: false })
  const [conImagen, setConImagen] = useState<Novedad | null>(null)
  const estado = useMutation({
    mutationFn: ({ id, nuevo }: { id: string; nuevo: EstadoPublicacion }) =>
      estadoNovedad(id, nuevo),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cms', 'novedades'] }),
  })

  return (
    <Panel
      title="Novedades"
      actions={
        <Button
          variant="primary"
          icon={Plus}
          onClick={() => {
            setEditando({ open: true })
          }}
        >
          Nueva novedad
        </Button>
      }
    >
      <div className="grid gap-4 border-b border-line px-5 py-4 sm:grid-cols-2 sm:px-6">
        <Select
          label="Estado"
          value={filtro.estado}
          onChange={(e) => {
            setFiltro({ page: 1, estado: e.target.value as EstadoPublicacion | '' })
          }}
          options={[
            { value: '', label: 'Todos' },
            ...Object.entries(ESTADO_PUBLICACION).map(([value, { label }]) => ({ value, label })),
          ]}
        />
      </div>
      {(query.isError || estado.isError) && (
        <div className="px-5 py-4 sm:px-6">
          <Alert tone="danger">{toProblem(query.error ?? estado.error).detail}</Alert>
        </div>
      )}
      <ul className="divide-y divide-line" aria-busy={query.isFetching}>
        {query.data?.items.length === 0 && (
          <li className="px-5 py-10 text-center text-ink-muted sm:px-6">
            {filtro.estado ? 'Ninguna novedad en este estado.' : 'Todavía no hay novedades.'}
          </li>
        )}
        {query.data?.items.map((n) => {
          const e = ESTADO_PUBLICACION[n.estado]
          return (
            <li
              key={n.id}
              className="flex flex-wrap items-start justify-between gap-3 px-5 py-4 sm:px-6"
            >
              <div className="flex min-w-0 gap-4">
                {n.imagen_url ? (
                  <img
                    src={n.imagen_url}
                    alt=""
                    className="hidden aspect-[3/2] w-24 shrink-0 rounded-control object-cover sm:block"
                  />
                ) : null}
                <div className="min-w-0">
                  <p className="font-semibold text-ink">{n.titulo}</p>
                  <p className="text-sm text-ink-muted">
                    {SECCION_NOVEDAD[n.seccion]} · /{n.slug}
                    {n.fecha_publicacion && ` · Publicada el ${fechaLarga(n.fecha_publicacion)}`}
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <StatusIndicator tone={e.tone} label={e.label} />
                <Button
                  variant="ghost"
                  icon={Pencil}
                  onClick={() => {
                    setEditando({ open: true, item: n })
                  }}
                >
                  Editar
                </Button>
                <Button
                  variant="ghost"
                  icon={ImagePlus}
                  onClick={() => {
                    setConImagen(n)
                  }}
                >
                  {n.imagen_url ? 'Imagen' : 'Agregar imagen'}
                </Button>
                {n.estado === 'PUBLICADO' ? (
                  <Button
                    variant="ghost"
                    icon={Archive}
                    onClick={() => {
                      estado.mutate({ id: n.id, nuevo: 'ARCHIVADO' })
                    }}
                  >
                    Archivar
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    icon={Send}
                    onClick={() => {
                      estado.mutate({ id: n.id, nuevo: 'PUBLICADO' })
                    }}
                  >
                    {n.estado === 'ARCHIVADO' ? 'Volver a publicar' : 'Publicar'}
                  </Button>
                )}
              </div>
            </li>
          )
        })}
      </ul>
      <Pagination
        page={filtro.page}
        pageSize={20}
        total={query.data?.total ?? 0}
        onPage={(page) => {
          setFiltro((f) => ({ ...f, page }))
        }}
      />
      <ImagenDialog
        key={conImagen?.id ?? 'sin-imagen'}
        novedad={conImagen}
        onClose={() => {
          setConImagen(null)
        }}
      />
      <NovedadDialog
        key={editando.item?.id ?? `nueva-${String(editando.open)}`}
        novedad={editando.item}
        open={editando.open}
        onClose={() => {
          setEditando({ open: false })
        }}
      />
    </Panel>
  )
}
