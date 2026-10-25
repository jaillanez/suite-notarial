import { Link } from 'react-router'

import logoUrl from '../assets/brand/logo-caja-notarial.webp'

export function BrandLogo({ to = '/' }: { to?: string }) {
  return (
    <Link to={to} className="flex shrink-0 items-center rounded-control">
      <img
        src={logoUrl}
        alt="Caja Notarial de San Juan — inicio"
        width={415}
        height={89}
        className="h-9 w-auto sm:h-11"
      />
    </Link>
  )
}
