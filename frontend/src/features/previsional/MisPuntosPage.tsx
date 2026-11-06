import { PageHeader } from '../../components/ui/Panel'
import { PuntosPanel } from './PuntosPanel'

/** El escribano consulta sus propios aportes y puntos (el backend no le muestra los de otro). */
export function MisPuntosPage() {
  return (
    <>
      <PageHeader
        title="Mis aportes y puntos"
        description="Aportes previsionales realizados y puntos acumulados conforme a la reglamentación de la Ley 7231, según los registros de la Caja."
      />
      <PuntosPanel />
    </>
  )
}
