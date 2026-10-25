import logoUrl from '../assets/brand/logo-caja-notarial.webp'

export function AppHeader() {
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex h-[4.5rem] max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
        <a href="/" className="flex shrink-0 items-center rounded-control">
          <img
            src={logoUrl}
            alt="Caja Notarial de San Juan"
            width={415}
            height={89}
            className="h-9 w-auto sm:h-11"
          />
        </a>
        <p className="text-sm font-medium text-ink-muted">Suite Notarial</p>
      </div>
    </header>
  )
}
