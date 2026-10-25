import { AppHeader } from './components/AppHeader'
import { SystemStatusPage } from './features/health/SystemStatusPage'

export function App() {
  return (
    <div className="min-h-dvh">
      <AppHeader />
      <SystemStatusPage />
    </div>
  )
}
