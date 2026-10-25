import { Copy, Download } from 'lucide-react'
import { useState } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'

interface RecoveryCodesProps {
  codes: string[]
  onDone: () => void
}

/** Muestra los códigos una sola vez; el usuario confirma que los guardó antes de seguir. */
export function RecoveryCodes({ codes, onDone }: RecoveryCodesProps) {
  const [saved, setSaved] = useState(false)
  const [copied, setCopied] = useState(false)
  const text = codes.join('\n')

  const copy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
  }
  const download = () => {
    const blob = new Blob(
      [
        `Suite Notarial · Caja Notarial de San Juan\nCódigos de recuperación (cada uno sirve una vez)\n\n${text}\n`,
      ],
      { type: 'text/plain;charset=utf-8' },
    )
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'suite-notarial-codigos-de-recuperacion.txt'
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-5">
      <Alert tone="warning" title="Guardalos ahora: no se vuelven a mostrar">
        Si perdés el teléfono, cada código te permite ingresar una vez. Guardalos fuera del
        teléfono, por ejemplo impresos o en un gestor de contraseñas.
      </Alert>
      <ol
        aria-label="Códigos de recuperación"
        className="grid grid-cols-1 gap-x-6 gap-y-2 rounded-control border border-line bg-surface-sunken px-5 py-4 font-mono text-base tracking-wider text-ink tabular-nums min-[420px]:grid-cols-2"
      >
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-3">
        <Button icon={Copy} onClick={() => void copy()}>
          {copied ? 'Copiados' : 'Copiar'}
        </Button>
        <Button icon={Download} onClick={download}>
          Descargar .txt
        </Button>
      </div>
      <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm font-medium text-ink">
        <input
          type="checkbox"
          checked={saved}
          onChange={(e) => {
            setSaved(e.target.checked)
          }}
          className="size-5 cursor-pointer accent-brand-800"
        />
        Guardé los códigos en un lugar seguro
      </label>
      <Button variant="primary" disabled={!saved} onClick={onDone}>
        Continuar
      </Button>
    </div>
  )
}
