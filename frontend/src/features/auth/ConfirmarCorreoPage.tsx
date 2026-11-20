import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MailCheck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { toProblem } from '../../lib/api'
import { confirmarCambioCorreo } from './api'
import { SESSION_KEY } from './session'

/** Lee el token del fragmento (no viaja al servidor) y lo borra de la barra de direcciones. */
function tokenDelFragmento(): string | null {
  const token = new URLSearchParams(window.location.hash.slice(1)).get('token')
  if (token) {
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
  }
  return token
}

/** Confirmación del nuevo correo de ingreso, desde el enlace que llegó a esa dirección. Se
 * confirma con un botón: abrir el enlace (o que lo abra un antivirus del correo) no alcanza. */
export function ConfirmarCorreoPage() {
  const [token] = useState(tokenDelFragmento)
  const queryClient = useQueryClient()
  const confirmar = useMutation({
    mutationFn: () => confirmarCambioCorreo(token ?? ''),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SESSION_KEY }),
  })

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-brand-900">
        Confirmar el nuevo correo
      </h1>
      <div className="mt-8 space-y-6">
        {!token && (
          <Alert tone="warning">
            Este enlace no tiene el código de confirmación. Abrilo tal cual llegó en el correo o
            pedí el cambio de nuevo desde Mi cuenta.
          </Alert>
        )}
        {confirmar.isError && <Alert tone="danger">{toProblem(confirmar.error).detail}</Alert>}
        {confirmar.isSuccess ? (
          <>
            <Alert tone="success">{confirmar.data}</Alert>
            <Link
              to="/ingresar"
              replace
              className="inline-flex min-h-11 items-center rounded-control bg-brand-800 px-4 text-sm font-semibold text-white no-underline hover:bg-brand-700"
            >
              Ir a ingresar
            </Link>
          </>
        ) : (
          token && (
            <>
              <p className="text-ink">
                Al confirmar, este pasa a ser el correo con el que ingresás a la Suite Notarial.
              </p>
              <Button
                variant="primary"
                icon={MailCheck}
                busy={confirmar.isPending}
                busyLabel="Confirmando…"
                onClick={() => {
                  confirmar.mutate()
                }}
              >
                Confirmar el nuevo correo
              </Button>
            </>
          )
        )}
      </div>
    </div>
  )
}
