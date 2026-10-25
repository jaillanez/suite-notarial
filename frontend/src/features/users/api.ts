import { api } from '../../lib/api'

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface UserRow {
  id: string
  email: string
  full_name: string
  cuit: string
  phone_number: string | null
  roles: string[]
  is_active: boolean
  suspension_reason: string | null
  suspended_at: string | null
  mfa_enabled: boolean
  last_login_at: string | null
  created_at: string
}

export interface RoleInfo {
  code: string
  name: string
  description: string | null
  mfa_required: boolean
  permissions: string[]
}

export interface UserFilters {
  page: number
  pageSize: number
  q: string
  status: 'all' | 'active' | 'suspended'
}

export interface NewUser {
  email: string
  full_name: string
  cuit: string
  phone_number: string | null
  roles: string[]
}

export async function fetchUsers(filters: UserFilters): Promise<Page<UserRow>> {
  const params: Record<string, string | number | boolean> = {
    page: filters.page,
    page_size: filters.pageSize,
  }
  if (filters.q.trim()) params.q = filters.q.trim()
  if (filters.status !== 'all') params.is_active = filters.status === 'active'
  return (await api.get<Page<UserRow>>('/v1/users', { params })).data
}

export async function fetchRoles(): Promise<RoleInfo[]> {
  return (await api.get<RoleInfo[]>('/v1/roles')).data
}

export async function createUser(data: NewUser): Promise<UserRow> {
  return (await api.post<UserRow>('/v1/users', data)).data
}

export async function setUserStatus(
  id: string,
  isActive: boolean,
  reason: string,
): Promise<UserRow> {
  return (await api.patch<UserRow>(`/v1/users/${id}/status`, { is_active: isActive, reason })).data
}

export async function setUserRoles(id: string, roles: string[]): Promise<UserRow> {
  return (await api.put<UserRow>(`/v1/users/${id}/roles`, { roles })).data
}
