import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Camera,
  Check,
  ChevronDown,
  ImagePlus,
  ScanText,
  TriangleAlert,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Select } from '../../components/ui/Select'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { toProblem } from '../../lib/api'
import { formatMoney, normalizeDecimalInput } from '../../lib/decimal'
import { actoCompleto, actoInput, type ActoForm } from '../ddjj/acto'
import { ActoCampos } from '../ddjj/ActoCampos'
import { fetchDeclaracion, type DeclaracionDetalle } from '../ddjj/api'
import { CATEGORIA, formatPeriodo, registroLabel } from '../ddjj/labels'
import { useVerificacionActo } from '../ddjj/verificacion'
import { ResultadoVerificacion } from '../ddjj/VerificacionActo'
import { CARGO, formatDate } from '../padron/labels'
import {
  analizarIndice,
  descartarSugerencia,
  fetchEstadoIa,
  ratificarActo,
  type Sugerencia,
} from './api'
import { AlertasSugerencia, AvisoHumano } from './componentes'
import { formularioDe } from './formulario'

const MAX_FOTOS = 6

// --------------------------------------------------------------------------- fotos

function Miniatura({ foto, onQuitar }: { foto: File; onQuitar: () => void }) {
  const url = useMemo(() => URL.createObjectURL(foto), [foto])
  useEffect(
    () => () => {
      URL.revokeObjectURL(url)
    },
    [url],
  )
  return (
    <li className="relative overflow-hidden rounded-control border border-line bg-surface-sunken">
      <img src={url} alt={foto.name} className="aspect-[3/4] w-full object-cover" />
      <button
        type="button"
        onClick={onQuitar}
        aria-label={`Quitar ${foto.name}`}
        className="absolute top-1.5 right-1.5 inline-flex size-9 cursor-pointer items-center justify-center rounded-full bg-surface/90 text-ink shadow-panel hover:bg-surface"
      >
        <X aria-hidden="true" className="size-4" strokeWidth={2.25} />
      </button>
    </li>
  )
}

function BotonFoto({
  icon: Icon,
  label,
  capture,
  onFotos,
}: {
  icon: typeof Camera
  label: string
  capture?: boolean
  onFotos: (fotos: File[]) => void
}) {
  return (
    <label className="inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-control border border-line-strong bg-surface px-4 text-sm font-semibold text-brand-800 transition-colors duration-150 ease-out-quint hover:border-brand-700 hover:bg-brand-50 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-action-600">
      <Icon aria-hidden="true" className="size-4" strokeWidth={2.25} />
      {label}
      <input
        type="file"
        accept="image/png,image/jpeg"
        multiple={!capture}
        capture={capture ? 'environment' : undefined}
        className="sr-only"
        onChange={(e) => {
          onFotos([...(e.target.files ?? [])])
          e.target.value = ''
        }}
      />
    </label>
  )
}

function EntradaFotos({
  ddjj,
  onLectura,
}: {
  ddjj: DeclaracionDetalle
  onLectura: (sugerencias: Sugerencia[]) => void
}) {
  const estado = useQuery({ queryKey: ['ia', 'estado'], queryFn: fetchEstadoIa })
  const [fotos, setFotos] = useState<File[]>([])
  const lectura = useMutation({
    mutationFn: () => analizarIndice(ddjj.id, fotos),
    onSuccess: (r) => {
      onLectura(r.sugerencias)
    },
  })
  const agregar = (nuevas: File[]) => {
    setFotos((f) => [...f, ...nuevas].slice(0, MAX_FOTOS))
  }
  const maxMb = estado.data?.max_mb ?? 10
  return (
    <Panel
      title="Fotos del índice del protocolo"
      description={`De frente, con buena luz y sin sombras: que se lean el número y la fecha de cada escritura. Podés sumar hasta ${String(MAX_FOTOS)} páginas (PNG o JPG de hasta ${String(maxMb)} MB).`}
    >
      <div className="grid gap-5 px-5 py-5 sm:px-6">
        {lectura.isError && <Alert tone="danger">{toProblem(lectura.error).detail}</Alert>}
        <div className="flex flex-wrap gap-3">
          <BotonFoto icon={Camera} label="Sacar una foto" capture onFotos={agregar} />
          <BotonFoto icon={ImagePlus} label="Elegir fotos" onFotos={agregar} />
        </div>
        {fotos.length > 0 && (
          <ul className="grid grid-cols-3 gap-3 sm:grid-cols-6" aria-label="Fotos para leer">
            {fotos.map((foto, i) => (
              <Miniatura
                key={`${foto.name}-${String(i)}`}
                foto={foto}
                onQuitar={() => {
                  setFotos((f) => f.filter((_, j) => j !== i))
                }}
              />
            ))}
          </ul>
        )}
        <div>
          <Button
            variant="primary"
            icon={ScanText}
            busy={lectura.isPending}
            busyLabel="Leyendo el índice…"
            disabled={fotos.length === 0}
            onClick={() => {
              lectura.mutate()
            }}
          >
            {fotos.length > 1 ? `Leer las ${String(fotos.length)} fotos` : 'Leer el índice'}
          </Button>
          {lectura.isPending && (
            <p className="mt-2 text-sm text-ink-muted" aria-live="polite">
              Puede tardar unos segundos por foto.
            </p>
          )}
        </div>
      </div>
    </Panel>
  )
}

// --------------------------------------------------------------------------- revisión

type EstadoRenglon =
  | { tipo: 'pendiente' }
  | { tipo: 'cargado' }
  | { tipo: 'error'; mensaje: string }
  | { tipo: 'descartado' }

interface Renglon {
  sugerencia: Sugerencia
  form: ActoForm
  incluir: boolean
  abierto: boolean
  estado: EstadoRenglon
}

/** El índice no dice quién autorizó cada escritura: la persona lo elige para todo el lote (salvo
 * que el registro tenga un solo escribano, donde no hay duda). Nunca se asigna en silencio. */
function escribanoUnico(ddjj: DeclaracionDetalle): string {
  return ddjj.escribanos.length === 1 ? (ddjj.escribanos[0]?.id ?? '') : ''
}

function renglonesDe(ddjj: DeclaracionDetalle, sugerencias: Sugerencia[]): Renglon[] {
  const escribano = escribanoUnico(ddjj)
  return sugerencias.map((s) => {
    const form = formularioDe(ddjj, s, escribano)
    const advertencias = s.alertas.some((a) => a.nivel === 'ADVERTENCIA')
    const repetido = s.alertas.some((a) => a.codigo === 'NUMERO_YA_DECLARADO')
    // El escribano se elige arriba para todos: su falta no abre cada renglón.
    const completo = actoCompleto({ ...form, escribano_id: form.escribano_id || 'elegido' })
    return {
      sugerencia: s,
      form,
      // Un número ya declarado probablemente es un renglón de otro mes: no se incluye solo.
      incluir: !repetido,
      abierto: advertencias || !completo,
      estado: { tipo: 'pendiente' },
    }
  })
}

function Resumen({ ddjj, form }: { ddjj: DeclaracionDetalle; form: ActoForm }) {
  const base = form.categoria === 'ESCRITURA_CON_VALOR' && form.base_imponible.trim()
  const escribano = ddjj.escribanos.find((e) => e.id === form.escribano_id)
  return (
    <span className="min-w-0 flex-1">
      <span className="block font-semibold text-ink tabular-nums">
        {form.numero_escritura ? `N° ${form.numero_escritura}` : 'Sin número'}
        <span className="font-normal text-ink-muted">
          {' · '}
          {form.fecha_acto ? formatDate(form.fecha_acto) : 'sin fecha'}
          {form.folio && ` · F. ${form.folio}`}
        </span>
      </span>
      <span className="block truncate text-sm text-ink">
        {form.naturaleza || 'Sin naturaleza'}
        <span className="text-ink-muted"> · {CATEGORIA[form.categoria].label}</span>
      </span>
      {base && (
        <span className="block text-sm text-ink tabular-nums">
          {formatMoney(normalizeDecimalInput(form.base_imponible))}
        </span>
      )}
      <span className="block truncate text-sm text-ink-muted">
        {escribano ? `Autorizó ${escribano.apellido_nombre}` : 'Falta elegir el escribano'}
      </span>
    </span>
  )
}

function Editor({
  ddjj,
  renglon,
  onChange,
}: {
  ddjj: DeclaracionDetalle
  renglon: Renglon
  onChange: (cambio: Partial<ActoForm>) => void
}) {
  const { verificacion, actualizando } = useVerificacionActo(ddjj.id, renglon.form)
  const leido = renglon.sugerencia.campos.naturaleza?.evidencia
  return (
    <div className="grid gap-4 border-t border-line px-5 py-4 sm:px-6">
      {leido && (
        <p className="text-sm text-ink-muted [overflow-wrap:anywhere]">
          Leído en la foto: <span className="text-ink">{leido}</span>
        </p>
      )}
      <AlertasSugerencia alertas={renglon.sugerencia.alertas} />
      <ActoCampos ddjj={ddjj} form={renglon.form} problem={null} onChange={onChange} />
      <ResultadoVerificacion verificacion={verificacion} actualizando={actualizando} />
    </div>
  )
}

function FilaRenglon({
  ddjj,
  renglon,
  onCambio,
}: {
  ddjj: DeclaracionDetalle
  renglon: Renglon
  onCambio: (cambio: Partial<Renglon>) => void
}) {
  const { estado } = renglon
  const cerrado = estado.tipo === 'cargado' || estado.tipo === 'descartado'
  const advertencias = renglon.sugerencia.alertas.filter((a) => a.nivel === 'ADVERTENCIA')
  return (
    <li
      className={
        estado.tipo === 'cargado'
          ? 'bg-success-50/50'
          : estado.tipo === 'error'
            ? 'bg-danger-50/40'
            : ''
      }
    >
      <div className="flex items-start gap-3 px-5 py-4 sm:px-6">
        <input
          type="checkbox"
          className="mt-1 size-5 shrink-0 accent-brand-800"
          aria-label={`Incluir la escritura ${renglon.form.numero_escritura || 'sin número'}`}
          checked={renglon.incluir}
          disabled={cerrado}
          onChange={(e) => {
            onCambio({ incluir: e.target.checked })
          }}
        />
        <Resumen ddjj={ddjj} form={renglon.form} />
        <span className="flex shrink-0 flex-col items-end gap-2">
          {estado.tipo === 'cargado' && (
            <span className="inline-flex items-center gap-1 text-sm font-semibold text-success-700">
              <Check aria-hidden="true" className="size-4" strokeWidth={2.5} />
              Cargado
            </span>
          )}
          {estado.tipo === 'pendiente' && advertencias.length > 0 && (
            <span className="inline-flex items-center gap-1 text-sm font-semibold text-warning-700">
              <TriangleAlert aria-hidden="true" className="size-4" strokeWidth={2.25} />
              Revisar
            </span>
          )}
          {!cerrado && (
            <button
              type="button"
              aria-expanded={renglon.abierto}
              onClick={() => {
                onCambio({ abierto: !renglon.abierto })
              }}
              className="inline-flex min-h-11 cursor-pointer items-center gap-1 rounded-control px-2 text-sm font-semibold text-brand-800 hover:bg-brand-50"
            >
              {renglon.abierto ? 'Cerrar' : 'Editar'}
              <ChevronDown
                aria-hidden="true"
                className={`size-4 transition-transform duration-150 ${renglon.abierto ? 'rotate-180' : ''}`}
              />
            </button>
          )}
        </span>
      </div>
      {estado.tipo === 'error' && (
        <div className="px-5 pb-3 sm:px-6">
          <Alert tone="danger">{estado.mensaje}</Alert>
        </div>
      )}
      {renglon.abierto && !cerrado && (
        <Editor
          ddjj={ddjj}
          renglon={renglon}
          onChange={(cambio) => {
            onCambio({ form: { ...renglon.form, ...cambio } })
          }}
        />
      )}
    </li>
  )
}

function Revision({
  ddjj,
  sugerencias,
  onOtraFoto,
}: {
  ddjj: DeclaracionDetalle
  sugerencias: Sugerencia[]
  onOtraFoto: () => void
}) {
  const client = useQueryClient()
  const [renglones, setRenglones] = useState(() => renglonesDe(ddjj, sugerencias))
  const [cargando, setCargando] = useState(false)
  const [aviso, setAviso] = useState<string | null>(null)
  const [escribanoLote, setEscribanoLote] = useState(() => escribanoUnico(ddjj))
  const elegirEscribano = (id: string) => {
    // Cambia los renglones que siguen con el del lote; los que se editaron uno por uno, no.
    setRenglones((rs) =>
      rs.map((r) =>
        r.estado.tipo !== 'cargado' && r.form.escribano_id === escribanoLote
          ? { ...r, form: { ...r.form, escribano_id: id } }
          : r,
      ),
    )
    setEscribanoLote(id)
    setAviso(null)
  }
  const cambiar = (i: number, cambio: Partial<Renglon>) => {
    setRenglones((rs) => rs.map((r, j) => (j === i ? { ...r, ...cambio } : r)))
  }
  const porCargar = renglones.filter((r) => r.incluir && r.estado.tipo !== 'cargado')
  const cargados = renglones.filter((r) => r.estado.tipo === 'cargado').length
  const terminado =
    cargados > 0 && renglones.every((r) => r.estado.tipo === 'cargado' || !r.incluir)

  const cargar = async () => {
    setAviso(null)
    if (renglones.some((r) => r.incluir && r.estado.tipo !== 'cargado' && !r.form.escribano_id)) {
      setAviso('Elegí el escribano que autorizó las escrituras.')
      return
    }
    const incompletos = renglones.filter(
      (r) => r.incluir && r.estado.tipo !== 'cargado' && !actoCompleto(r.form),
    )
    if (incompletos.length > 0) {
      setRenglones((rs) => rs.map((r) => (incompletos.includes(r) ? { ...r, abierto: true } : r)))
      setAviso(
        `Faltan datos en ${String(incompletos.length)} ${incompletos.length === 1 ? 'renglón' : 'renglones'}: completalos o destildalos.`,
      )
      return
    }
    setCargando(true)
    // De a uno y en orden: cada acto pasa por los controles del libro con los anteriores ya
    // cargados (número repetido, orden de fechas).
    let fallidos = 0
    for (const [i, r] of renglones.entries()) {
      if (!r.incluir || r.estado.tipo === 'cargado') continue
      try {
        await ratificarActo(r.sugerencia.id, actoInput(r.form))
        cambiar(i, { estado: { tipo: 'cargado' }, abierto: false })
      } catch (error) {
        fallidos += 1
        cambiar(i, { estado: { tipo: 'error', mensaje: toProblem(error).detail }, abierto: true })
      }
    }
    if (fallidos === 0) {
      // Lo que no se incluyó queda descartado (y auditado), no pendiente para siempre.
      for (const [i, r] of renglones.entries()) {
        if (r.incluir || r.estado.tipo !== 'pendiente') continue
        cambiar(i, { estado: { tipo: 'descartado' } })
        void descartarSugerencia(r.sugerencia.id, 'No incluido al revisar el índice.').catch(
          () => undefined,
        )
      }
    }
    await client.invalidateQueries({ queryKey: ['ddjj'] })
    setCargando(false)
  }

  return (
    <div className="grid gap-6">
      <AvisoHumano>
        Revisá cada renglón contra el libro antes de cargarlo. Tocá «Editar» para corregir un dato y
        destildá los que no van en esta declaración.
      </AvisoHumano>
      <Panel
        title={`${String(renglones.length)} ${renglones.length === 1 ? 'renglón leído' : 'renglones leídos'}`}
        description={`${registroLabel(ddjj.registro)} · ${formatPeriodo(ddjj.periodo)}`}
        actions={
          <Button icon={Camera} onClick={onOtraFoto} disabled={cargando}>
            Otra foto
          </Button>
        }
      >
        <div className="border-b border-line px-5 py-4 sm:px-6">
          <Select
            label="Escribano que autorizó estas escrituras"
            value={escribanoLote}
            disabled={cargando}
            onChange={(e) => {
              elegirEscribano(e.target.value)
            }}
            options={[
              ...(escribanoLote ? [] : [{ value: '', label: 'Elegí el escribano…' }]),
              ...ddjj.escribanos.map((e) => ({
                value: e.id,
                label: `${e.apellido_nombre} · ${CARGO[e.cargo]} · Mat. ${String(e.matricula_numero)}`,
              })),
            ]}
          />
          <p className="mt-1.5 text-sm text-ink-muted">
            El índice no lo dice. Si alguna escritura es de otro escribano, cambialo en ese renglón.
          </p>
        </div>
        <ul className="divide-y divide-line">
          {renglones.map((r, i) => (
            <FilaRenglon
              key={r.sugerencia.id}
              ddjj={ddjj}
              renglon={r}
              onCambio={(cambio) => {
                cambiar(i, cambio)
              }}
            />
          ))}
        </ul>
        <div className="grid gap-3 border-t border-line bg-surface-sunken px-5 py-4 sm:px-6">
          {aviso && <Alert tone="warning">{aviso}</Alert>}
          {terminado ? (
            <Alert
              tone="success"
              action={
                <Link to={`/ddjj/${ddjj.id}`} className="font-semibold">
                  Volver a la declaración
                </Link>
              }
            >
              {cargados === 1 ? 'Se cargó 1 acto.' : `Se cargaron ${String(cargados)} actos.`}
            </Alert>
          ) : (
            <div>
              <Button
                variant="primary"
                icon={Check}
                busy={cargando}
                busyLabel="Cargando…"
                disabled={porCargar.length === 0}
                onClick={() => {
                  void cargar()
                }}
              >
                {porCargar.length === 1
                  ? 'Cargar 1 acto'
                  : `Cargar ${String(porCargar.length)} actos`}
              </Button>
            </div>
          )}
        </div>
      </Panel>
    </div>
  )
}

// --------------------------------------------------------------------------- página

export function IndicePage() {
  const { id = '' } = useParams()
  const ddjj = useQuery({
    queryKey: ['ddjj', 'declaracion', id],
    queryFn: () => fetchDeclaracion(id),
  })
  const [lectura, setLectura] = useState<Sugerencia[] | null>(null)
  const d = ddjj.data
  const operable = d && d.estado === 'BORRADOR' && d.puede_operar

  return (
    <>
      <Link
        to={`/ddjj/${id}`}
        className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-medium"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Volver a la declaración
      </Link>
      <PageHeader
        title="Cargar actos desde el índice"
        description="Sacale una foto al índice del protocolo: la Suite lee cada escritura y vos revisás y confirmás antes de cargarlas."
      />
      {ddjj.isPending && (
        <div aria-busy="true" className="h-64 animate-pulse rounded-panel bg-brand-50" />
      )}
      {ddjj.isError && <Alert tone="danger">{toProblem(ddjj.error).detail}</Alert>}
      {d && !operable && (
        <Alert tone="warning">
          Solo se cargan actos en una declaración en borrador de un registro donde tenés cargo.
        </Alert>
      )}
      {d &&
        operable &&
        (lectura ? (
          <Revision
            key={lectura.map((s) => s.id).join()}
            ddjj={d}
            sugerencias={lectura}
            onOtraFoto={() => {
              setLectura(null)
            }}
          />
        ) : (
          <EntradaFotos ddjj={d} onLectura={setLectura} />
        ))}
    </>
  )
}
