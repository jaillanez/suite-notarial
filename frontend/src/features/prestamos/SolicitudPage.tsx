import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, FilePlus2 } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { FileField } from '../../components/ui/FileField'
import { PageHeader, Panel } from '../../components/ui/Panel'
import { Select } from '../../components/ui/Select'
import { TextArea } from '../../components/ui/TextArea'
import { toProblem } from '../../lib/api'
import { useSession } from '../auth/session'
import { normalizeDecimalInput } from '../../lib/decimal'
import { MAX_BYTES, TIPOS_ACEPTADOS } from '../pagos/labels'
import { cargarDocumento, crearSolicitud, fetchLineas, simular, type TipoDocumento } from './api'
import {
  CondicionesLinea,
  EscribanoPicker,
  PlanCuotas,
  RequisitosLinea,
  ResumenEvaluacion,
} from './componentes'
import {
  LEYENDA_USD,
  MONEDA,
  TIPO_DOCUMENTO,
  documentosDeLinea,
  fueraDeLinea,
  topeCapital,
  topeCuotas,
  importe,
} from './labels'

const DECIMAL = /^\d+(\.\d{1,2})?$/
const TIPOS = new Set(TIPOS_ACEPTADOS.split(','))

/** Lo que el navegador ya sabe del archivo; el servidor vuelve a validar por contenido. */
function errorDeArchivo(archivo: File | null): string | undefined {
  if (!archivo) return undefined
  if (archivo.size > MAX_BYTES) return 'Supera los 10 MB.'
  if (archivo.type && !TIPOS.has(archivo.type)) return 'Tiene que ser un PDF, PNG o JPG.'
  return undefined
}

export function SolicitudPage() {
  const navigate = useNavigate()
  const { can } = useSession()
  // El personal carga la solicitud de cualquier escribano; el escribano, la suya.
  const personal = can('prestamos:manage')
  const [params] = useSearchParams()
  const lineas = useQuery({ queryKey: ['prestamos', 'lineas'], queryFn: fetchLineas })
  const activas = (lineas.data ?? []).filter((l) => l.is_active)
  const [form, setForm] = useState({
    escribano: '',
    garante: '',
    linea: params.get('linea') ?? '',
    capital: params.get('capital') ?? '',
    cuotas: params.get('cuotas') ?? '',
    ingreso: '',
    observaciones: '',
  })
  const linea = activas.find((l) => l.id === form.linea) ?? activas[0]
  const usd = linea?.moneda === 'USD'
  const simbolo = MONEDA[linea?.moneda ?? 'ARS'].simbolo
  const datos = useDeferredValue({
    capital: normalizeDecimalInput(form.capital),
    cuotas: Number.parseInt(form.cuotas, 10),
    ingreso: normalizeDecimalInput(form.ingreso),
    escribano: form.escribano,
    garante: form.garante,
  })
  // Requisitos que se adjuntan con la solicitud (también se pueden agregar después).
  const [archivos, setArchivos] = useState<Partial<Record<TipoDocumento, File>>>({})
  const [otro, setOtro] = useState<{ descripcion: string; archivo: File | null }>({
    descripcion: '',
    archivo: null,
  })
  const requeridos = linea ? documentosDeLinea(linea) : []
  const adjuntos: { tipo: TipoDocumento; descripcion: string; archivo: File }[] = [
    ...requeridos.flatMap((t) => {
      const archivo = archivos[t]
      return archivo ? [{ tipo: t, descripcion: '', archivo }] : []
    }),
    ...(otro.archivo
      ? [{ tipo: 'OTRO' as const, descripcion: otro.descripcion.trim(), archivo: otro.archivo }]
      : []),
  ]
  const adjuntosValidos =
    adjuntos.every((a) => !errorDeArchivo(a.archivo)) &&
    (!otro.archivo || otro.descripcion.trim().length > 0)
  const errores = fueraDeLinea(linea, datos.capital, datos.cuotas)
  const completo =
    Boolean(linea) &&
    !errores.capital &&
    !errores.cuotas &&
    (!personal || Boolean(datos.escribano)) &&
    DECIMAL.test(datos.capital) &&
    datos.cuotas > 0 &&
    DECIMAL.test(datos.ingreso)
  const evaluacion = useQuery({
    queryKey: ['prestamos', 'evaluacion', linea?.id, datos],
    queryFn: () =>
      simular({
        linea_id: linea?.id ?? '',
        capital: datos.capital,
        cuotas: datos.cuotas,
        ingreso_neto: datos.ingreso,
        escribano_id: personal ? datos.escribano : null,
        garante_escribano_id: datos.garante || null,
      }),
    enabled: completo,
    placeholderData: keepPreviousData,
    retry: false,
  })
  const guardar = useMutation({
    mutationFn: async () => {
      const p = await crearSolicitud({
        escribano_id: personal ? form.escribano : null,
        linea_id: linea?.id ?? '',
        capital: datos.capital,
        cuotas: datos.cuotas,
        ingreso_neto: datos.ingreso,
        garante_escribano_id: form.garante || null,
        observaciones: form.observaciones.trim() || null,
      })
      // Los requisitos van al expediente de la solicitud recién creada. Si alguno falla, la
      // solicitud ya está cargada: lo que falte se agrega desde su pantalla.
      for (const a of adjuntos) {
        try {
          await cargarDocumento(p.id, a)
        } catch {
          break
        }
      }
      return p
    },
    onSuccess: (p) => {
      void navigate(`/prestamos/${p.id}`)
    },
  })
  const set = (key: keyof typeof form) => (valor: string) => {
    setForm((f) => ({ ...f, [key]: valor }))
  }
  const viable = evaluacion.data !== undefined && evaluacion.data.impedimentos.length === 0

  return (
    <>
      <Link
        to="/prestamos"
        className="mb-6 inline-flex min-h-11 items-center gap-2 text-sm font-medium"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={2.25} />
        Préstamos
      </Link>
      <PageHeader
        title={personal ? 'Nueva solicitud de préstamo' : 'Solicitar un préstamo'}
        description={
          personal
            ? 'Se evalúa mientras completás los datos. La solicitud la resuelve otra persona con permiso para otorgar.'
            : 'Se evalúa mientras completás los datos. La Caja revisa la solicitud y te avisa si la otorga.'
        }
      />
      <div className="grid items-start gap-6 lg:grid-cols-[24rem_minmax(0,1fr)]">
        <Panel title="Solicitud">
          <div className="grid gap-5 px-5 py-4 sm:px-6">
            {personal && (
              <EscribanoPicker
                label="Escribano"
                value={form.escribano}
                onChange={set('escribano')}
              />
            )}
            <Select
              label="Línea de crédito"
              value={linea?.id ?? ''}
              onChange={(e) => {
                set('linea')(e.target.value)
              }}
              options={activas.map((l) => ({
                value: l.id,
                label: l.es_ejemplo ? `${l.nombre} (a confirmar)` : l.nombre,
              }))}
            />
            {linea && (
              <div className="grid gap-3">
                <CondicionesLinea linea={linea} />
                <RequisitosLinea linea={linea} />
              </div>
            )}
            <div className="grid grid-cols-2 gap-4">
              <Field
                label={`Capital (${simbolo})`}
                inputMode="decimal"
                className="[&_input]:tabular-nums"
                hint={linea && `Hasta ${importe(linea.monto_maximo, linea.moneda)}.`}
                error={errores.capital}
                value={form.capital}
                onChange={(e) => {
                  set('capital')(topeCapital(linea, e.target.value))
                }}
              />
              <Field
                label="Cuotas"
                inputMode="numeric"
                className="[&_input]:tabular-nums"
                hint={linea && `De ${String(linea.plazo_minimo)} a ${String(linea.plazo_maximo)}.`}
                error={errores.cuotas}
                value={form.cuotas}
                onChange={(e) => {
                  set('cuotas')(topeCuotas(linea, e.target.value))
                }}
              />
            </div>
            <Field
              label={`Ingreso neto mensual ${usd ? 'en dólares ' : ''}(${simbolo})`}
              inputMode="decimal"
              hint={
                usd
                  ? LEYENDA_USD
                  : 'Promedio acreditado, neto de retenciones. Tiene que alcanzar al menos el ingreso mínimo que se calcula al lado.'
              }
              className="[&_input]:tabular-nums"
              value={form.ingreso}
              onChange={(e) => {
                set('ingreso')(e.target.value)
              }}
            />
            <EscribanoPicker
              label={linea?.requiere_garante ? 'Garante (obligatorio)' : 'Garante (opcional)'}
              value={form.garante}
              excluir={form.escribano}
              opcional={!linea?.requiere_garante}
              soloGarantes={!personal}
              onChange={set('garante')}
            />
            <fieldset className="grid gap-4">
              <legend className="text-sm font-semibold text-ink">Requisitos</legend>
              <p className="-mt-2 text-sm text-ink-muted">
                Adjuntalos ahora o después, desde la solicitud. PDF, PNG o JPG de hasta 10 MB.
              </p>
              {requeridos.map((t) => (
                <FileField
                  key={t}
                  label={TIPO_DOCUMENTO[t]}
                  accept={TIPOS_ACEPTADOS}
                  formatos="La línea lo exige para otorgar"
                  archivo={archivos[t] ?? null}
                  error={errorDeArchivo(archivos[t] ?? null)}
                  onChange={(archivo) => {
                    setArchivos((x) => ({ ...x, [t]: archivo ?? undefined }))
                  }}
                />
              ))}
              <Field
                label="Otro documento (opcional)"
                maxLength={200}
                placeholder="Por ejemplo: boletas de impuestos"
                error={
                  otro.archivo && !otro.descripcion.trim() ? 'Decí qué documento es.' : undefined
                }
                value={otro.descripcion}
                onChange={(e) => {
                  setOtro((x) => ({ ...x, descripcion: e.target.value }))
                }}
              />
              <FileField
                label="Archivo del otro documento"
                accept={TIPOS_ACEPTADOS}
                formatos="PDF, PNG o JPG de hasta 10 MB"
                archivo={otro.archivo}
                error={errorDeArchivo(otro.archivo)}
                onChange={(archivo) => {
                  setOtro((x) => ({ ...x, archivo }))
                }}
              />
            </fieldset>
            <TextArea
              label="Observaciones (opcional)"
              maxLength={2000}
              value={form.observaciones}
              onChange={(e) => {
                set('observaciones')(e.target.value)
              }}
            />
          </div>
          <div className="flex justify-end border-t border-line bg-surface-sunken px-5 py-4 sm:px-6">
            <Button
              variant="primary"
              icon={FilePlus2}
              busy={guardar.isPending}
              busyLabel="Cargando…"
              disabled={!completo || !viable || !adjuntosValidos || evaluacion.isPlaceholderData}
              onClick={() => {
                guardar.mutate()
              }}
            >
              {personal ? 'Cargar solicitud' : 'Enviar solicitud'}
            </Button>
          </div>
        </Panel>
        <div
          aria-live="polite"
          className={`grid gap-6 transition-opacity duration-150 ${evaluacion.isPlaceholderData ? 'opacity-60' : ''}`}
        >
          {guardar.isError && <Alert tone="danger">{toProblem(guardar.error).detail}</Alert>}
          {!completo && (
            <Panel>
              <p className="px-5 py-10 text-center text-ink-muted sm:px-6">
                Elegí el escribano y completá capital, cuotas e ingreso neto para evaluar.
              </p>
            </Panel>
          )}
          {completo && evaluacion.isError && (
            <Alert tone="danger">{toProblem(evaluacion.error).detail}</Alert>
          )}
          {completo && evaluacion.data && (
            <>
              <ResumenEvaluacion ev={evaluacion.data} conIngreso />
              <Panel title="Cuadro de amortización (proyectado)">
                <PlanCuotas
                  plan={evaluacion.data.plan}
                  totales={evaluacion.data.totales}
                  conEstado={false}
                  moneda={evaluacion.data.moneda}
                />
              </Panel>
            </>
          )}
        </div>
      </div>
    </>
  )
}
