import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ESCRIBANO, renderWithProviders } from '../../test/render'
import * as authApi from './api'
import { ContrasenaPanel, PerfilPanel } from './CuentaPaneles'

vi.mock('./api')

const PERFIL: authApi.Perfil = {
  email: 'caja@suite-notarial.example',
  full_name: 'Caja Demo',
  cuit: '20-00000500-3',
  phone_number: null,
  nombre_editable: false,
}

describe('perfil', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('solo se edita el teléfono: nombre, correo y CUIT los administra la Caja', async () => {
    vi.mocked(authApi.fetchPerfil).mockResolvedValue(PERFIL)
    vi.mocked(authApi.actualizarPerfil).mockResolvedValue({
      ...PERFIL,
      phone_number: '264 555-0101',
    })
    renderWithProviders(<PerfilPanel />, { user: ESCRIBANO })

    const guardar = await screen.findByRole('button', { name: 'Guardar cambios' })
    expect(guardar).toBeDisabled()
    expect(screen.getByText(PERFIL.full_name)).toBeInTheDocument()
    expect(screen.getByText(PERFIL.email)).toBeInTheDocument()
    // Sin campo para el nombre ni para el correo.
    expect(screen.queryByRole('textbox', { name: 'Nombre y apellido' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Correo electrónico')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Teléfono (opcional)'), {
      target: { value: '264 555-0101' },
    })
    fireEvent.click(guardar)

    await waitFor(() => {
      expect(authApi.actualizarPerfil).toHaveBeenCalledWith({ phone_number: '264 555-0101' })
    })
    expect(await screen.findByText('Tus datos se guardaron.')).toBeInTheDocument()
  })
})

describe('contraseña', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('pide la actual, una nueva que cumpla la política y la repetición', async () => {
    vi.mocked(authApi.cambiarContrasena).mockResolvedValue(
      'La contraseña se cambió. Cerramos tus sesiones en otros dispositivos.',
    )
    renderWithProviders(<ContrasenaPanel />, { user: ESCRIBANO })

    const boton = screen.getByRole('button', { name: 'Cambiar contraseña' })
    fireEvent.change(screen.getByLabelText('Contraseña actual'), {
      target: { value: 'Prueba-Segura-2026!' },
    })
    fireEvent.change(screen.getByLabelText('Contraseña nueva'), { target: { value: 'corta' } })
    expect(boton).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Contraseña nueva'), {
      target: { value: 'Otra-Clave-Segura-2026!' },
    })
    fireEvent.change(screen.getByLabelText('Repetí la contraseña nueva'), {
      target: { value: 'Otra-Clave-Distinta-2026!' },
    })
    expect(screen.getByText('Las contraseñas no coinciden.')).toBeInTheDocument()
    expect(boton).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Repetí la contraseña nueva'), {
      target: { value: 'Otra-Clave-Segura-2026!' },
    })
    fireEvent.click(boton)

    expect(await screen.findByText(/La contraseña se cambió/)).toBeInTheDocument()
    expect(authApi.cambiarContrasena).toHaveBeenCalledWith(
      'Prueba-Segura-2026!',
      'Otra-Clave-Segura-2026!',
    )
    // Los campos quedan vacíos.
    expect(screen.getByLabelText('Contraseña actual')).toHaveValue('')
  })
})
