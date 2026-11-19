import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { useEffect, useMemo } from 'react'

import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { toProblem } from '../../lib/api'
import { fetchDeclaracionPdf, nombreDeclaracionPdf } from './api'

/** Vista previa del PDF de la DDJJ: se ve antes de descargarlo. */
export function VistaPreviaPdf({
  ddjj,
  titulo,
  open,
  onClose,
}: {
  ddjj: { id: string; periodo: string; registro: { numero_registro: number } }
  titulo: string
  open: boolean
  onClose: () => void
}) {
  const query = useQuery({
    queryKey: ['ddjj', 'declaracion', ddjj.id, 'pdf'],
    queryFn: () => fetchDeclaracionPdf(ddjj.id),
    enabled: open,
    // Cada apertura trae el PDF del momento (el borrador cambia al cargar actos).
    gcTime: 0,
    staleTime: 0,
  })
  const url = useMemo(() => (query.data ? URL.createObjectURL(query.data) : null), [query.data])
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url)
    },
    [url],
  )
  const nombre = nombreDeclaracionPdf(ddjj)

  return (
    <Dialog
      open={open}
      size="ancho"
      title={titulo}
      description="Revisalo antes de descargarlo. Es el mismo documento que se imprime."
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cerrar</Button>
          {url ? (
            <a
              href={url}
              download={nombre}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-control border border-brand-800 bg-brand-800 px-4 text-sm font-semibold text-white no-underline hover:border-brand-700 hover:bg-brand-700"
            >
              <Download aria-hidden="true" className="size-4" strokeWidth={2.25} />
              Descargar
            </a>
          ) : (
            <Button variant="primary" icon={Download} disabled>
              Descargar
            </Button>
          )}
        </>
      }
    >
      {query.isError && <Alert tone="danger">{toProblem(query.error).detail}</Alert>}
      {query.isPending && open && (
        <div
          className="h-[70dvh] animate-pulse rounded-control bg-brand-50"
          aria-busy="true"
          aria-label="Generando el PDF…"
        />
      )}
      {url && (
        <iframe
          src={url}
          title={titulo}
          className="h-[70dvh] w-full rounded-control border border-line bg-surface-sunken"
        />
      )}
    </Dialog>
  )
}
