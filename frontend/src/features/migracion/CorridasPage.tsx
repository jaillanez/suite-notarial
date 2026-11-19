import { StatusIndicator } from '../../components/StatusIndicator'
import { PageHeader } from '../../components/ui/Panel'
import type { Corrida } from './api'
import { BoletasSinRegistro } from './BoletasSinRegistro'

export function Cuadra({ corrida }: { corrida: Pick<Corrida, 'cuadra' | 'estado'> }) {
  if (corrida.cuadra === null) return <StatusIndicator tone="unknown" label="Sin cuadratura" />
  return corrida.cuadra ? (
    <StatusIndicator tone="success" label="Cuadra" />
  ) : (
    <StatusIndicator tone="danger" label="No cuadra" />
  )
}

/** Migración del sistema anterior: lo que queda por resolver a mano, las boletas migradas sin
 * registro. El detalle de cada corrida sigue en `/migracion/:id`. */
export function CorridasPage() {
  return (
    <>
      <PageHeader
        title="Migración del sistema anterior"
        description="Boletas que vinieron del sistema anterior sin registro asignado: la Caja les asigna el registro que corresponde."
      />
      <BoletasSinRegistro />
    </>
  )
}
