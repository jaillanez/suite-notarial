import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, ScanText, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { FileField } from '../../components/ui/FileField'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import {
  compararDecimal,
  formatDecimal,
  formatMoney,
  normalizeDecimalInput,
} from '../../lib/decimal'
import { actoCompleto, actoInput, actoVacio, type ActoForm } from '../ddjj/acto'
import { ActoCampos } from '../ddjj/ActoCampos'
import {
  fetchDeclaracion,
  type CategoriaActo,
  type DeclaracionDetalle,
  type TipoProtocolo,
} from '../ddjj/api'
import { CATEGORIA, PROTOCOLO, formatPeriodo, registroLabel } from '../ddjj/labels'
import { CARGO, formatDate } from '../padron/labels'
import {
  analizarMinuta,
  descartarSugerencia,
  fetchEstadoIa,
  ratificarActo,
  type Sugerencia,
} from './api'
import {
  AlertasSugerencia,
  AvisoHumano,
  ConfirmacionHumana,
  PistaCampo,
  Respaldo,
} from './componentes'

const ETIQUETAS: Record<keyof ActoForm, string> = {
  escribano_id: 'Escribano',
  categoria: 'Tipo de acto',
  tipo_protocolo: 'Protocolo',
  numero_escritura: 'N° de escritura',
  folio: 'Folio',
  fecha_acto: 'Fecha del acto',
  naturaleza: 'Naturaleza',
  base_imponible: 'Base imponible',
}

function esImporte(valor: string): boolean {
  return /^\d+(\.\d+)?$/.test(valor)
}

// --------------------------------------------------------------------------- entrada

function EntradaMinuta({
  ddjj,
  onSugerencia,
}: {
  ddjj: DeclaracionDetalle
  onSugerencia: (s: Sugerencia) => void
}) {
  const estado = useQuery({
    queryKey: ['ia', 'estado'],
    queryFn: fetchEstadoIa,
    staleTime: 300_000,
  })
  // Solo se avisa que falta el OCR cuando el servidor lo confirma (no mientras carga).
  const ocr = estado.data?.ocr_disponible !== false
  const maxMb = estado.data?.max_mb ?? 10
  const [modo, setModo] = useState<'archivo' | 'texto'>('archivo')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [texto, setTexto] = useState('')
  const leer = useMutation({
    mutationFn: () =>
      analizarMinuta(ddjj.id, modo === 'archivo' && archivo ? { archivo } : { texto }),
    onSuccess: onSugerencia,
  })
  const problem = leer.isError ? toProblem(leer.error) : null
  const listo = modo === 'archivo' ? archivo !== null : texto.trim().length > 0

  return (
    <div className="max-w-[48rem] space-y-6">
      <AvisoHumano>
        La Suite lee la minuta en los servidores de la Caja, sin enviarla a servicios externos, y
        propone los datos del acto con el fragmento que respalda cada uno. Nada se agrega a la
        declaración hasta que lo revises y confirmes. El documento no se guarda.
      </AvisoHumano>
      <Panel title="Minuta o borrador de escritura">
        <div className="space-y-5 px-5 py-5 sm:px-6">
          <fieldset>
            <legend className="text-sm font-medium text-ink">Cómo la cargás</legend>
            <div className="mt-2 flex flex-wrap gap-x-6 gap-y-2">
              {(
                [
                  ['archivo', 'Subir el archivo'],
                  ['texto', 'Pegar el texto'],
                ] as const
              ).map(([valor, etiqueta]) => (
                <label
                  key={valor}
                  className="flex min-h-11 cursor-pointer items-center gap-2.5 text-sm font-medium text-ink"
                >
                  <input
                    type="radio"
                    name="modo"
                    value={valor}
                    checked={modo === valor}
                    onChange={() => {
                      setModo(valor)
                      leer.reset()
                    }}
                    className="size-5 cursor-pointer accent-brand-800"
                  />
                  {etiqueta}
                </label>
              ))}
            </div>
          </fieldset>
          {modo === 'archivo' ? (
            <FileField
              label="Archivo de la minuta"
              accept={ocr ? 'application/pdf,image/png,image/jpeg' : 'application/pdf'}
              formatos={
                ocr
                  ? `PDF con texto, o foto o escaneo en PNG o JPG, de hasta ${String(maxMb)} MB`
                  : `PDF con texto de hasta ${String(maxMb)} MB (la lectura de imágenes no está disponible en este servidor)`
              }
              archivo={archivo}
              onChange={(f) => {
                setArchivo(f)
                leer.reset()
              }}
            />
          ) : (
            <TextArea
              label="Texto de la minuta"
              rows={10}
              value={texto}
              hint="Pegá el texto completo: encabezado, comparecencia y precio o monto."
              onChange={(e) => {
                setTexto(e.target.value)
              }}
            />
          )}
          {problem && <Alert tone="danger">{problem.detail}</Alert>}
          <div className="flex justify-end">
            <Button
              icon={ScanText}
              busy={leer.isPending}
              busyLabel="Leyendo la minuta…"
              disabled={!listo}
              onClick={() => {
                leer.mutate()
              }}
            >
              Leer la minuta
            </Button>
          </div>
        </div>
      </Panel>
    </div>
  )
}

// --------------------------------------------------------------------------- revisión

function formularioDe(ddjj: DeclaracionDetalle, s: Sugerencia): ActoForm {
  const v = (k: keyof ActoForm) => s.campos[k]?.valor ?? null
  const vacio = actoVacio(ddjj)
  const escribano = v('escribano_id')
  const base = v('base_imponible')
  return {
    // Si la Suite no identificó al autorizante, lo elige la persona: no se preselecciona nadie.
    escribano_id: escribano && ddjj.escribanos.some((e) => e.id === escribano) ? escribano : '',
    categoria: (v('categoria') ?? vacio.categoria) as CategoriaActo,
    tipo_protocolo: (v('tipo_protocolo') ?? vacio.tipo_protocolo) as TipoProtocolo,
    numero_escritura: v('numero_escritura') ?? '',
    folio: v('folio') ?? '',
    fecha_acto: v('fecha_acto') ?? '',
    naturaleza: v('naturaleza') ?? '',
    base_imponible: base && base !== '0.00' ? formatDecimal(base) : '',
  }
}

function RevisionMinuta({
  ddjj,
  sugerencia,
  onDescartada,
}: {
  ddjj: DeclaracionDetalle
  sugerencia: Sugerencia
  onDescartada: () => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form, setForm] = useState(() => formularioDe(ddjj, sugerencia))
  const [revisado, setRevisado] = useState(false)
  const confirmar = useMutation({
    mutationFn: () => ratificarActo(sugerencia.id, actoInput(form)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ddjj', 'declaracion', ddjj.id] })
      await queryClient.invalidateQueries({ queryKey: ['ddjj', 'declaraciones'] })
      void navigate(`/ddjj/${ddjj.id}`)
    },
  })
  const descartar = useMutation({
    mutationFn: () => descartarSugerencia(sugerencia.id),
    onSuccess: onDescartada,
  })
  const problem = confirmar.isError ? toProblem(confirmar.error) : null

  const nombre = (id: string) => {
    const e = ddjj.escribanos.find((x) => x.id === id)
    return e ? `${e.apellido_nombre} (${CARGO[e.cargo]})` : 'otro escribano'
  }
  const mostrar = (campo: string, valor: string): string => {
    switch (campo) {
      case 'escribano_id':
        return nombre(valor)
      case 'categoria':
        return CATEGORIA[valor as CategoriaActo].label
      case 'tipo_protocolo':
        return PROTOCOLO[valor as TipoProtocolo]
      case 'fecha_acto':
        return formatDate(valor)
      case 'base_imponible':
        return formatMoney(valor)
      default:
        return valor
    }
  }
  const pista = (campo: keyof ActoForm) => {
    let actual = form[campo]
    if (campo === 'base_imponible') {
      const normalizado = normalizeDecimalInput(actual)
      const sugeridoBase = sugerencia.campos.base_imponible?.valor
      actual =
        sugeridoBase && esImporte(normalizado) && compararDecimal(normalizado, sugeridoBase) === 0
          ? sugeridoBase
          : normalizado
    }
    return (
      <PistaCampo
        campo={sugerencia.campos[campo]}
        actual={actual}
        mostrar={(v) => mostrar(campo, v)}
      />
    )
  }
  const pistas = Object.fromEntries(
    (Object.keys(ETIQUETAS) as (keyof ActoForm)[]).map((k) => [k, pista(k)]),
  )
  const advertencias = sugerencia.alertas.filter((a) => a.nivel === 'ADVERTENCIA').length

  return (
    <div className="space-y-6">
      <AvisoHumano>
        Revisá cada dato contra la minuta y corregí lo que haga falta. El aporte lo calcula la Caja
        al presentar la declaración: la Suite no propone importes de aporte.
      </AvisoHumano>
      <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
        <Panel
          title="Lo que leyó la Suite"
          description={`${String(Object.values(sugerencia.campos).filter((c) => c.valor !== null).length)} de ${String(Object.keys(sugerencia.campos).length)} datos encontrados${advertencias ? ` · ${String(advertencias)} ${advertencias === 1 ? 'advertencia' : 'advertencias'}` : ''}`}
          footer={
            <p className="text-xs text-ink-muted">
              Motor {sugerencia.motor} {sugerencia.motor_version}
              {sugerencia.entrada.ocr && ` · OCR (${sugerencia.entrada.ocr})`}
              {sugerencia.entrada.caracteres !== null &&
                ` · ${sugerencia.entrada.caracteres.toLocaleString('es-AR')} caracteres leídos`}
            </p>
          }
        >
          {sugerencia.alertas.length > 0 && (
            <div className="border-b border-line px-5 py-4 sm:px-6">
              <AlertasSugerencia alertas={sugerencia.alertas} />
            </div>
          )}
          <Respaldo campos={sugerencia.campos} etiquetas={ETIQUETAS} mostrar={mostrar} />
        </Panel>
        <div className="space-y-4">
          <Panel
            title="Datos del acto"
            description={`Se agrega a la declaración de ${formatPeriodo(ddjj.periodo)} cuando confirmes.`}
          >
            <div className="space-y-4 px-5 py-5 sm:px-6">
              {problem && <Alert tone="danger">{problem.detail}</Alert>}
              <ActoCampos
                ddjj={ddjj}
                form={form}
                problem={problem}
                pistas={pistas}
                onChange={(cambio) => {
                  setForm((f) => ({ ...f, ...cambio }))
                  setRevisado(false)
                }}
              />
            </div>
          </Panel>
          <ConfirmacionHumana checked={revisado} onChange={setRevisado}>
            Revisé los datos contra la minuta y confirmo que corresponden al acto.
          </ConfirmacionHumana>
          {descartar.isError && <Alert tone="danger">{toProblem(descartar.error).detail}</Alert>}
          <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <Button
              icon={X}
              busy={descartar.isPending}
              busyLabel="Descartando…"
              onClick={() => {
                descartar.mutate()
              }}
            >
              Descartar y leer otra
            </Button>
            <Button
              variant="primary"
              icon={Check}
              busy={confirmar.isPending}
              busyLabel="Agregando…"
              disabled={!revisado || !actoCompleto(form)}
              onClick={() => {
                confirmar.mutate()
              }}
            >
              Confirmar y agregar el acto
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- página

export function MinutaPage() {
  const { id = '' } = useParams()
  const ddjj = useQuery({
    queryKey: ['ddjj', 'declaracion', id],
    queryFn: () => fetchDeclaracion(id),
  })
  const [sugerencia, setSugerencia] = useState<Sugerencia | null>(null)
  const d = ddjj.data

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
        title="Cargar un acto desde la minuta"
        description={
          d
            ? `${registroLabel(d.registro)} · ${formatPeriodo(d.periodo)}. La Suite propone los datos; vos los revisás y confirmás.`
            : 'La Suite propone los datos; vos los revisás y confirmás.'
        }
      />
      {ddjj.isPending && (
        <div aria-busy="true" className="h-64 animate-pulse rounded-panel bg-brand-50" />
      )}
      {ddjj.isError && <Alert tone="danger">{toProblem(ddjj.error).detail}</Alert>}
      {d && !(d.estado === 'BORRADOR' && d.puede_operar) && (
        <Alert tone="warning">
          Solo se cargan actos en una declaración en borrador de un registro donde tenés cargo.
        </Alert>
      )}
      {d &&
        d.estado === 'BORRADOR' &&
        d.puede_operar &&
        (sugerencia ? (
          <RevisionMinuta
            key={sugerencia.id}
            ddjj={d}
            sugerencia={sugerencia}
            onDescartada={() => {
              setSugerencia(null)
            }}
          />
        ) : (
          <EntradaMinuta ddjj={d} onSugerencia={setSugerencia} />
        ))}
    </>
  )
}
