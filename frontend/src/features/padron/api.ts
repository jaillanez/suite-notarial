import { api } from '../../lib/api'
import type { Page } from '../users/api'

export type EstadoMatricula = 'ACTIVO' | 'SUSPENDIDO' | 'CESANTE' | 'JUBILADO' | 'FALLECIDO'
export type Cargo = 'TITULAR' | 'ADSCRIPTO' | 'SUPLENTE_INTERINO'
export type EstadoRegistro = 'ACTIVO' | 'VACANTE' | 'CERRADO'

export interface Circunscripcion {
  id: string
  nombre: string
  descripcion: string | null
  is_active: boolean
}

export interface CargoResumen {
  adscripcion_id: string
  escribano_id: string
  matricula_numero: number
  apellido_nombre: string
  cargo: Cargo
  fecha_desde: string
  estado_matricula: EstadoMatricula
}

export interface Registro {
  id: string
  numero_registro: number
  nombre_fantasia: string | null
  circunscripcion: Circunscripcion
  departamento: string
  domicilio_legal: string
  telefono: string | null
  email: string | null
  fecha_creacion: string | null
  estado: EstadoRegistro
  titular: CargoResumen | null
  cantidad_adscriptos: number
}

export interface RegistroDetalle extends Registro {
  cargos_vigentes: CargoResumen[]
}

export interface Persona {
  id: string
  cuit: string
  tipo_documento: string
  numero_documento: string
  apellido: string
  nombre: string
  fecha_nacimiento: string | null
  email: string | null
  telefono: string | null
  domicilio_real: string | null
}

export interface Escribano {
  id: string
  matricula_numero: number
  tomo: string | null
  folio: string | null
  fecha_matriculacion: string
  estado_matricula: EstadoMatricula
  apellido_nombre: string
  cuit: string
  numero_documento: string
  registro_actual: number | null
  cargo_actual: Cargo | null
  tiene_cuenta: boolean
}

export interface CargoItem {
  id: string
  registro_id: string
  numero_registro: number
  cargo: Cargo
  resolucion_designacion: string | null
  fecha_desde: string
  fecha_hasta: string | null
  motivo_cierre: string | null
  is_current: boolean
}

export interface HistorialItem {
  id: string
  estado_anterior: EstadoMatricula
  estado_nuevo: EstadoMatricula
  motivo: string
  resolucion_respaldo: string | null
  fecha_efectiva: string
  fecha_cambio: string
  operador_email: string | null
}

export interface EscribanoDetalle extends Escribano {
  persona: Persona
  motivo_ultimo_cambio_estado: string | null
  fecha_ultimo_cambio_estado: string | null
  cargos: CargoItem[]
  historial: HistorialItem[]
}

export interface EscribanoFilters {
  page: number
  pageSize: number
  q: string
  estado: EstadoMatricula | ''
  registroNumero: string
  departamento: string
}

export interface PersonaInput {
  cuit: string
  tipo_documento: string
  numero_documento: string
  apellido: string
  nombre: string
  fecha_nacimiento: string | null
  email: string | null
  telefono: string | null
  domicilio_real: string | null
}

export interface EscribanoInput {
  persona: PersonaInput
  matricula_numero: number
  tomo: string | null
  folio: string | null
  fecha_matriculacion: string
}

export interface RegistroInput {
  numero_registro: number
  nombre_fantasia: string | null
  circunscripcion_id: string
  departamento: string
  domicilio_legal: string
  telefono: string | null
  email: string | null
  fecha_creacion: string | null
}

const P = '/v1/padron'

export async function fetchDepartamentos(): Promise<string[]> {
  return (await api.get<string[]>(`${P}/departamentos`)).data
}

export async function fetchCircunscripciones(): Promise<Circunscripcion[]> {
  return (await api.get<Circunscripcion[]>(`${P}/circunscripciones`)).data
}

export async function createCircunscripcion(nombre: string, descripcion: string | null) {
  return (await api.post<Circunscripcion>(`${P}/circunscripciones`, { nombre, descripcion })).data
}

export async function updateCircunscripcion(
  id: string,
  changes: Partial<Pick<Circunscripcion, 'nombre' | 'descripcion' | 'is_active'>>,
) {
  return (await api.patch<Circunscripcion>(`${P}/circunscripciones/${id}`, changes)).data
}

export async function fetchEscribanos(f: EscribanoFilters): Promise<Page<Escribano>> {
  const params: Record<string, string | number> = { page: f.page, page_size: f.pageSize }
  if (f.q.trim()) params.q = f.q.trim()
  if (f.estado) params.estado = f.estado
  if (/^\d+$/.test(f.registroNumero)) params.registro_numero = Number(f.registroNumero)
  if (f.departamento) params.departamento = f.departamento
  return (await api.get<Page<Escribano>>(`${P}/escribanos`, { params })).data
}

export async function fetchEscribano(id: string): Promise<EscribanoDetalle> {
  return (await api.get<EscribanoDetalle>(`${P}/escribanos/${id}`)).data
}

export async function createEscribano(data: EscribanoInput): Promise<EscribanoDetalle> {
  return (await api.post<EscribanoDetalle>(`${P}/escribanos`, data)).data
}

export async function updateEscribano(
  id: string,
  data: { tomo?: string | null; folio?: string | null; persona?: Partial<PersonaInput> },
): Promise<EscribanoDetalle> {
  return (await api.patch<EscribanoDetalle>(`${P}/escribanos/${id}`, data)).data
}

export async function changeEstado(
  id: string,
  data: {
    nuevo_estado: EstadoMatricula
    motivo: string
    resolucion_respaldo: string | null
    fecha_efectiva: string
  },
): Promise<EscribanoDetalle> {
  return (await api.post<EscribanoDetalle>(`${P}/escribanos/${id}/estado`, data)).data
}

export async function assignCargo(
  id: string,
  data: {
    registro_id: string
    cargo: Cargo
    fecha_desde: string
    resolucion_designacion: string | null
  },
): Promise<EscribanoDetalle> {
  return (await api.post<EscribanoDetalle>(`${P}/escribanos/${id}/cargos`, data)).data
}

export async function closeCargo(id: string, fechaHasta: string, motivo: string) {
  return (
    await api.post<CargoItem>(`${P}/cargos/${id}/cierre`, { fecha_hasta: fechaHasta, motivo })
  ).data
}

export async function createCuenta(id: string, email: string): Promise<EscribanoDetalle> {
  return (await api.post<EscribanoDetalle>(`${P}/escribanos/${id}/cuenta`, { email })).data
}

export async function fetchRegistros(params: {
  page: number
  pageSize: number
  q: string
  departamento: string
  estado: EstadoRegistro | ''
}): Promise<Page<Registro>> {
  const query: Record<string, string | number> = {
    page: params.page,
    page_size: params.pageSize,
  }
  if (params.q.trim()) query.q = params.q.trim()
  if (params.departamento) query.departamento = params.departamento
  if (params.estado) query.estado = params.estado
  return (await api.get<Page<Registro>>(`${P}/registros`, { params: query })).data
}

export async function fetchRegistro(id: string): Promise<RegistroDetalle> {
  return (await api.get<RegistroDetalle>(`${P}/registros/${id}`)).data
}

export async function createRegistro(data: RegistroInput): Promise<Registro> {
  return (await api.post<Registro>(`${P}/registros`, data)).data
}

export async function updateRegistro(
  id: string,
  data: Partial<Omit<RegistroInput, 'numero_registro'>>,
): Promise<Registro> {
  return (await api.patch<Registro>(`${P}/registros/${id}`, data)).data
}

export async function closeRegistro(id: string, motivo: string): Promise<Registro> {
  return (await api.post<Registro>(`${P}/registros/${id}/cierre`, { motivo })).data
}
