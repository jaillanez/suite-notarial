import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, Pencil, Plus, Send } from 'lucide-react'
import { useState } from 'react'

import { StatusIndicator } from '../../components/StatusIndicator'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Field } from '../../components/ui/Field'
import { Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import {
  actualizarPagina,
  crearPagina,
  estadoPagina,
  fetchPaginas,
  type EstadoPublicacion,
  type GrupoPagina,
  type Pagina,
} from './api'
import { ESTADO_PUBLICACION, GRUPO_PAGINA, fechaLarga } from './labels'

function PaginaDialog({
  pagina,
  open,
  onClose,
}: {
  pagina?: Pagina
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    grupo: pagina?.grupo ?? 'CAJA',
    titulo: pagina?.titulo ?? '',
    contenido: pagina?.contenido ?? '',
    orden: String(pagina?.orden ?? 0),
    slug: pagina?.slug ?? '',
  })
  const publicada = pagina !== undefined && pagina.estado !== 'BORRADOR'
  const save = useMutation({
    mutationFn: () => {
      const data = {
        grupo: form.grupo,
        titulo: form.titulo.trim(),
        contenido: form.contenido.trim(),
        orden: Number(form.orden) || 0,
        slug: form.slug.trim() || null,
      }
      return pagina ? actualizarPagina(pagina.id, data) : crearPagina(data)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['cms', 'paginas'] })
      await queryClient.invalidateQueries({ queryKey: ['sitio'] })
      onClose()
    },
  })
  const problem = save.isError ? toProblem(save.error) : null
  const bind = (key: 'titulo' | 'contenido' | 'orden' | 'slug') => ({
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
      title={pagina ? 'Editar página' : 'Nueva página'}
      description={
        publicada
          ? 'Está publicada: los cambios se ven en el sitio apenas guardes.'
          : 'Se guarda como borrador; aparece en el menú del sitio cuando la publicás.'
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
        <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
          <Select
            label="Menú"
            value={form.grupo}
            onChange={(e) => {
              setForm((f) => ({ ...f, grupo: e.target.value as GrupoPagina }))
            }}
            options={Object.entries(GRUPO_PAGINA).map(([value, label]) => ({ value, label }))}
          />
          <Field label="Orden" inputMode="numeric" hint="Menor, más arriba." {...bind('orden')} />
        </div>
        <Field label="Título" maxLength={200} {...bind('titulo')} />
        <TextArea
          label="Contenido"
          rows={12}
          hint="Texto sin formato. Separá los párrafos con una línea en blanco."
          {...bind('contenido')}
        />
        <Field
          label="Enlace"
          placeholder="se-arma-con-el-titulo"
          disabled={publicada}
          hint={
            publicada
              ? 'El enlace de una página publicada no cambia.'
              : 'Opcional: minúsculas, números y guiones. Vacío, se arma con el título.'
          }
          {...bind('slug')}
        />
      </div>
    </Dialog>
  )
}

export function PaginasAdmin() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['cms', 'paginas'], queryFn: fetchPaginas })
  const [editando, setEditando] = useState<{ open: boolean; item?: Pagina }>({ open: false })
  const estado = useMutation({
    mutationFn: ({ id, nuevo }: { id: string; nuevo: EstadoPublicacion }) =>
      estadoPagina(id, nuevo),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['cms', 'paginas'] })
      await queryClient.invalidateQueries({ queryKey: ['sitio'] })
    },
  })

  return (
    <Panel
      title="Páginas institucionales"
      description="Las páginas fijas de los menús Caja y Normativa del sitio (Quiénes somos, Ley de creación, Reglamentación…). Autoridades y Estados contables se arman solos con sus secciones."
      actions={
        <Button
          variant="primary"
          icon={Plus}
          onClick={() => {
            setEditando({ open: true })
          }}
        >
          Nueva página
        </Button>
      }
    >
      {(query.isError || estado.isError) && (
        <div className="px-5 py-4 sm:px-6">
          <Alert tone="danger">{toProblem(query.error ?? estado.error).detail}</Alert>
        </div>
      )}
      {query.isPending && (
        <div aria-busy="true" className="grid gap-3 px-5 py-5 sm:px-6">
          <span className="sr-only">Cargando las páginas…</span>
          <span className="block h-14 animate-pulse rounded-control bg-brand-50" />
          <span className="block h-14 animate-pulse rounded-control bg-brand-50" />
        </div>
      )}
      <ul className="divide-y divide-line">
        {query.data?.length === 0 && (
          <li className="px-5 py-10 text-center text-ink-muted sm:px-6">
            Todavía no hay páginas. Empezá por «Quiénes somos».
          </li>
        )}
        {query.data?.map((p) => {
          const e = ESTADO_PUBLICACION[p.estado]
          return (
            <li
              key={p.id}
              className="flex flex-wrap items-start justify-between gap-3 px-5 py-4 sm:px-6"
            >
              <div className="min-w-0">
                <p className="font-semibold text-ink">{p.titulo}</p>
                <p className="text-sm text-ink-muted">
                  Menú {GRUPO_PAGINA[p.grupo]} · /{p.slug} · Actualizada el{' '}
                  {fechaLarga(p.updated_at)}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <StatusIndicator tone={e.tone} label={e.label} />
                <Button
                  variant="ghost"
                  icon={Pencil}
                  onClick={() => {
                    setEditando({ open: true, item: p })
                  }}
                >
                  Editar
                </Button>
                {p.estado === 'PUBLICADO' ? (
                  <Button
                    variant="ghost"
                    icon={Archive}
                    onClick={() => {
                      estado.mutate({ id: p.id, nuevo: 'ARCHIVADO' })
                    }}
                  >
                    Archivar
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    icon={Send}
                    onClick={() => {
                      estado.mutate({ id: p.id, nuevo: 'PUBLICADO' })
                    }}
                  >
                    {p.estado === 'ARCHIVADO' ? 'Volver a publicar' : 'Publicar'}
                  </Button>
                )}
              </div>
            </li>
          )
        })}
      </ul>
      <PaginaDialog
        key={editando.item?.id ?? `nueva-${String(editando.open)}`}
        pagina={editando.item}
        open={editando.open}
        onClose={() => {
          setEditando({ open: false })
        }}
      />
    </Panel>
  )
}
