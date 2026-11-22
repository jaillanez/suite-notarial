import { fireEvent, screen, waitFor } from '@testing-library/react'
import { AxiosError, AxiosHeaders } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders, ESCRIBANO } from '../../test/render'
import * as authApi from './api'
import { LoginPage } from './LoginPage'

vi.mock('./api')

function axios401(detail: string) {
  return new AxiosError('401', 'ERR', undefined, undefined, {
    status: 401,
    statusText: 'Unauthorized',
    headers: {},
    config: { headers: new AxiosHeaders() },
    data: { status: 401, title: 'Unauthorized', detail, type: 'about:blank' },
  })
}

function fillCredentials() {
  fireEvent.change(screen.getByLabelText('Correo electrónico o CUIT'), {
    target: { value: 'escribano@suite-notarial.example' },
  })
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'Clave-Segura-1!' } })
  fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }))
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('pasa por el segundo factor antes de entrar', async () => {
    vi.mocked(authApi.login).mockResolvedValue({ status: 'mfa_required', user: null })
    vi.mocked(authApi.loginMfa).mockResolvedValue({
      status: 'authenticated',
      user: { ...ESCRIBANO, mfa_enabled: true, mfa_verified: true },
    })
    renderWithProviders(<LoginPage />, {
      path: '/ingresar',
      routes: [{ path: '/', element: <p>Inicio</p> }],
    })

    fillCredentials()
    expect(await screen.findByText('Verificación en dos pasos')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Código de verificación'), {
      target: { value: '123456' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Verificar e ingresar' }))

    expect(await screen.findByText('Inicio')).toBeInTheDocument()
    expect(authApi.loginMfa).toHaveBeenCalledWith('123456', false)
  })

  it('pide el código que llegó por correo y permite reenviarlo', async () => {
    vi.mocked(authApi.login).mockResolvedValue({
      status: 'mfa_required',
      user: null,
      mfa_method: 'email',
      email_hint: 'h***@gmail.com',
    })
    vi.mocked(authApi.reenviarCodigo).mockResolvedValue({
      status: 'mfa_required',
      user: null,
      mfa_method: 'email',
      email_hint: 'h***@gmail.com',
    })
    vi.mocked(authApi.loginMfa).mockResolvedValue({
      status: 'authenticated',
      user: { ...ESCRIBANO, mfa_verified: true },
    })
    renderWithProviders(<LoginPage />, {
      path: '/ingresar',
      routes: [{ path: '/', element: <p>Inicio</p> }],
    })

    fillCredentials()
    expect(await screen.findByText('Revisá tu correo')).toBeInTheDocument()
    expect(screen.getByText('h***@gmail.com')).toBeInTheDocument()
    expect(screen.queryByText('No tengo acceso a la aplicación')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Mandarme otro código' }))
    expect(await screen.findByText(/Te mandamos un código nuevo/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Código del correo'), {
      target: { value: '12 34-56' },
    })
    fireEvent.click(screen.getByLabelText('No volver a pedirlo en este equipo por 30 días'))
    fireEvent.click(screen.getByRole('button', { name: 'Verificar e ingresar' }))
    expect(await screen.findByText('Inicio')).toBeInTheDocument()
    expect(authApi.loginMfa).toHaveBeenCalledWith('123456', true)
  })

  it('muestra el error genérico del servidor', async () => {
    vi.mocked(authApi.login).mockRejectedValue(axios401('Las credenciales no son válidas.'))
    renderWithProviders(<LoginPage />, { path: '/ingresar' })

    fillCredentials()

    expect(await screen.findByRole('alert')).toHaveTextContent('Las credenciales no son válidas.')
  })

  it('permite usar un código de recuperación', async () => {
    vi.mocked(authApi.login).mockResolvedValue({ status: 'mfa_required', user: null })
    renderWithProviders(<LoginPage />, { path: '/ingresar' })

    fillCredentials()
    fireEvent.click(await screen.findByRole('button', { name: 'No tengo acceso a la aplicación' }))

    await waitFor(() => {
      expect(screen.getByLabelText('Código de recuperación')).toHaveFocus()
    })
  })
})
