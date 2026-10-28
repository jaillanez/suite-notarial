import type { LucideIcon } from 'lucide-react'
import {
  BadgeCheck,
  FilePenLine,
  HandCoins,
  Landmark,
  Megaphone,
  ReceiptText,
  Wallet,
} from 'lucide-react'

import type { PaginaMenu } from '../cms/api'

export interface EnlaceMenu {
  to: string
  label: string
}

export interface GrupoMenu {
  label: string
  enlaces: EnlaceMenu[]
}

/** Servicios online: los trámites del afiliado. Los que piden sesión llevan al ingreso. */
export const SERVICIOS: (EnlaceMenu & { icon: LucideIcon; detalle: string })[] = [
  {
    to: '/prestamos/simular',
    label: 'Solicitar préstamo',
    detalle: 'Simulá la cuota antes de pedirlo',
    icon: HandCoins,
  },
  {
    to: '/prestamos',
    label: 'Pagar cuota de préstamo',
    detalle: 'Cuotas, vencimientos y saldo',
    icon: Wallet,
  },
  {
    to: '/ddjj',
    label: 'Generar declaración jurada',
    detalle: 'Escrituras del mes y su aporte',
    icon: FilePenLine,
  },
  {
    to: '/ddjj',
    label: 'Pagar aportes',
    detalle: 'Boleta, Mercado Pago o comprobante',
    icon: ReceiptText,
  },
  {
    to: '/sitio/novedades?seccion=COMUNICADOS',
    label: 'Comunicados de la Caja',
    detalle: 'Avisos para los afiliados',
    icon: Megaphone,
  },
  {
    to: '/sitio/documentos',
    label: 'Estados contables',
    detalle: 'Publicados con su huella',
    icon: Landmark,
  },
  {
    to: '/verificar',
    label: 'Verificar una boleta',
    detalle: 'Con el código impreso en ella',
    icon: BadgeCheck,
  },
]

/** Menú principal, con el mismo orden que el sitio de siempre de la Caja. Las páginas
 * institucionales salen del gestor; las secciones fijas, de la Suite. */
export function grupos(paginas: PaginaMenu[]): GrupoMenu[] {
  const de = (grupo: PaginaMenu['grupo']) =>
    paginas
      .filter((p) => p.grupo === grupo)
      .map((p) => ({ to: `/sitio/paginas/${p.slug}`, label: p.titulo }))
  return [
    {
      label: 'Caja',
      enlaces: [
        ...de('CAJA'),
        { to: '/sitio/autoridades', label: 'Autoridades' },
        { to: '/sitio/documentos', label: 'Estados contables' },
      ],
    },
    {
      label: 'Normativa',
      enlaces: [...de('NORMATIVA'), { to: '/sitio/documentos', label: 'Documentos oficiales' }],
    },
    {
      label: 'Servicios online',
      enlaces: SERVICIOS.map(({ to, label }) => ({ to, label })),
    },
  ]
}
