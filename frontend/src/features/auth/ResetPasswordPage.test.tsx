import { fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/render'
import * as authApi from './api'
import { ResetPasswordPage } from './ResetPasswordPage'

vi.mock('./api')

describe('ResetPasswordPage', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/')
    vi.resetAllMocks()
  })

  it('toma el token del fragmento y lo borra de la URL', async () => {
    window.history.replaceState(null, '', '/restablecer-clave#token=abc123def456ghi789jkl')
    vi.mocked(authApi.confirmPasswordReset).mockResolvedValue('La contraseña se actualizó.')
    renderWithProviders(<ResetPasswordPage />, { path: '/restablecer-clave' })

    expect(window.location.hash).toBe('')
    const submit = screen.getByRole('button', { name: 'Guardar contraseña' })
    fireEvent.change(screen.getByLabelText('Contraseña nueva'), { target: { value: 'corta' } })
    expect(submit).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Contraseña nueva'), {
      target: { value: 'Nueva-Clave-2026!' },
    })
    fireEvent.change(screen.getByLabelText('Repetí la contraseña'), {
      target: { value: 'Nueva-Clave-2026!' },
    })
    fireEvent.click(submit)

    expect(await screen.findByText('Contraseña actualizada')).toBeInTheDocument()
    expect(authApi.confirmPasswordReset).toHaveBeenCalledWith(
      'abc123def456ghi789jkl',
      'Nueva-Clave-2026!',
    )
  })

  it('avisa si el enlace no trae token', () => {
    window.history.replaceState(null, '', '/restablecer-clave')
    renderWithProviders(<ResetPasswordPage />, { path: '/restablecer-clave' })

    expect(screen.getByText('Enlace incompleto')).toBeInTheDocument()
  })
})
