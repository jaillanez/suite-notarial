# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Dos audiencias con peso equivalente en el uso diario:

- **Escribanos de San Juan** (titulares y adscriptos), autogestionando desde su escribanía, en PC y en celular: declaraciones juradas mensuales de escrituras, emisión y pago de boletas de aportes, carga de comprobantes, consultas de estado de cuenta, préstamos y servicios previsionales.
- **Personal interno de la Caja Notarial** (Tesorería, administración, auditoría), en escritorio durante la jornada: padrón, parámetros de aportes, conciliación de pagos, reportes y exportaciones, publicación institucional.

## Product Purpose

Suite integral de la Caja Notarial de San Juan que reemplaza el sistema legado: gestiona el padrón de escribanos, el cálculo y la emisión de boletas de aportes previsionales, la conciliación de pagos, los préstamos y el sitio institucional. El éxito es que cada peso aportado sea trazable al centavo, que ningún cálculo dependa del cliente, y que tanto el escribano como Tesorería resuelvan su trámite sin pasar por ventanilla.

## Positioning

Es el sistema oficial de la propia Caja: sus boletas, saldos y parámetros son la fuente de verdad previsional. La integridad contable (decimales exactos, vigencias inmutables, auditoría de cada acción sensible) y la ratificación humana de todo acto son la propuesta, no un agregado.

## Operating Context

- Ciclo mensual: el escribano declara escrituras del período (DDJJ), el backend liquida y emite la boleta oficial (PDF con QR y código de barras), el escribano paga y adjunta comprobante, Tesorería concilia.
- Un comprobante adjunto no es un pago confirmado: queda `PENDIENTE_REVISION` hasta que Tesorería lo valida.
- Estados de matrícula: `ACTIVO`, `SUSPENDIDO`, `CESANTE`. No existe borrado físico de afiliados, matrículas, parámetros ni liquidaciones.
- La IA es solo asistencial (OCR de DNI, extracción de minutas): sus salidas son `SUGERIDO_POR_IA` y requieren ratificación de un humano.
- Personal interno trabaja con grillas grandes con paginación en servidor y exportaciones XLSX/CSV cuyos totales deben coincidir con la pantalla.

## Capabilities and Constraints

- Stack: FastAPI + PostgreSQL (backend), React + TypeScript estricto + Tailwind (frontend). Sin Docker en desarrollo.
- Especificación funcional por módulo en `Docs/modulo-01` … `Docs/modulo-11`; playbook de fases en `AGENTS.md`.
- Terminología del dominio en español rioplatense: escribano, matrícula, adscripto, titular, circunscripción, DDJJ, boleta, aporte, vigencia, conciliación, Tesorería.
- Parámetros de negocio reales (alícuotas, topes, formato de boleta) aún no están definidos: se marcan `TODO(negocio)` y nunca se presentan como oficiales.

## Brand Commitments

- Nombre institucional: **Caja Notarial de San Juan**.
- La Caja tiene logo y colores institucionales; el usuario los va a proveer. Hasta entonces la identidad visual es provisional y debe poder reemplazarse ajustando tokens, sin rediseñar componentes.

## Evidence on Hand

- Documentación técnica y de requerimientos en `Docs/` (PDFs de arquitectura e ingeniería, borrador de requerimientos `.docx`, módulos en markdown).
- Ausentes por ahora: logo, paleta oficial, fotografía, datos reales. No se fabrican.

## Product Principles

1. La exactitud manda sobre la velocidad: un número mostrado es un número que la Caja respalda.
2. Estado siempre explícito: el usuario sabe en qué estado está cada trámite (pendiente, conciliado, rechazado) y quién debe actuar.
3. El humano ratifica: ninguna automatización sella actos ni mueve saldos.
4. Un mismo sistema para escribano y personal interno, sin que ninguno cargue con la complejidad del otro.

## Accessibility & Inclusion

WCAG 2.2 nivel AA como piso en toda la suite (contraste, operación completa por teclado, foco visible, tamaño de objetivos táctiles, lectores de pantalla). Uso real en celular por escribanos.
