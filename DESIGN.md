---
name: Suite Notarial · Caja Notarial de San Juan
description: Sistema oficial de la Caja Notarial de San Juan; claro, sobrio y exacto, con el azul petróleo del isologo como voz institucional.
colors:
  petroleo-institucional: "#113347"
  petroleo-profundo: "#0b2433"
  petroleo-medio: "#1b4762"
  petroleo-velo: "#dce6ec"
  petroleo-bruma: "#eef3f6"
  azul-accion: "#1a76d1"
  azul-accion-profundo: "#135ea8"
  tinta: "#16232b"
  tinta-secundaria: "#4c5c66"
  tinta-tenue: "#63737d"
  linea: "#d3dce2"
  linea-firme: "#b4c2ca"
  lienzo: "#f3f6f8"
  superficie: "#ffffff"
  superficie-hundida: "#f7f9fa"
  exito: "#1b6e40"
  exito-tinte: "#e8f4ed"
  advertencia: "#845300"
  advertencia-tinte: "#fdf3dc"
  peligro: "#a8201a"
  peligro-tinte: "#fcebea"
typography:
  headline:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.333
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.556
  body:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  body-sm:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.429
  label:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.429
  caption:
    fontFamily: "Public Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.333
rounded:
  control: "6px"
  panel: "8px"
  pill: "9999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "8": "32px"
  "10": "40px"
  "14": "56px"
components:
  button-secondary:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.petroleo-institucional}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "44px"
  button-secondary-hover:
    backgroundColor: "{colors.petroleo-bruma}"
    textColor: "{colors.petroleo-institucional}"
  button-secondary-active:
    backgroundColor: "{colors.petroleo-velo}"
    textColor: "{colors.petroleo-institucional}"
  status-success:
    backgroundColor: "{colors.exito-tinte}"
    textColor: "{colors.exito}"
    rounded: "{rounded.pill}"
    padding: "4px 12px 4px 8px"
  status-warning:
    backgroundColor: "{colors.advertencia-tinte}"
    textColor: "{colors.advertencia}"
    rounded: "{rounded.pill}"
    padding: "4px 12px 4px 8px"
  status-danger:
    backgroundColor: "{colors.peligro-tinte}"
    textColor: "{colors.peligro}"
    rounded: "{rounded.pill}"
    padding: "4px 12px 4px 8px"
  status-unknown:
    backgroundColor: "{colors.superficie-hundida}"
    textColor: "{colors.tinta-secundaria}"
    rounded: "{rounded.pill}"
    padding: "4px 12px 4px 8px"
  panel:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.panel}"
  panel-row:
    padding: "16px 24px"
  panel-footer:
    backgroundColor: "{colors.superficie-hundida}"
    textColor: "{colors.tinta-secundaria}"
    typography: "{typography.caption}"
    padding: "12px 24px"
  app-header:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta-secundaria}"
    height: "72px"
---

# Design System: Suite Notarial · Caja Notarial de San Juan

## Overview

**Creative North Star: "El Protocolo a la Vista"**

La Suite es el libro oficial de la Caja abierto sobre el escritorio: papel claro, tinta oscura, sello petróleo. Cada pantalla se lee como un registro ordenado de hechos verificables (un estado, una hora, un importe) y nunca como una vitrina. La luz de oficina de día manda: tema claro, lienzo gris frío apenas teñido de petróleo, superficies blancas que alojan la información y una sola voz de marca, el azul petróleo del isologo (#113347), reservada para títulos, acciones y la cabecera institucional.

La densidad es de oficina, no de tablero: filas generosas (16px vertical), etiquetas a la izquierda y valores a la derecha, ancho de lectura acotado a 65ch. La profundidad es mínima y ambiental; el orden lo dan las líneas finas y el cambio de superficie, no las sombras. El estado se declara siempre con ícono y palabra, porque el color solo no es un dato que la Caja pueda respaldar.

La identidad parte de activos oficiales: el logo de la Caja (isotipo petróleo con plumín de estilográfica, logotipo pizarra #21323B) y el azul de acción del sitio institucional (#1A76D1). Todo valor de marca vive en tokens de `@theme`, de modo que un ajuste de identidad se resuelve en `frontend/src/index.css` sin rediseñar componentes.

**Key Characteristics:**
- Tema claro único (`color-scheme: light`), pensado para escritorio y celular con luz diurna.
- Una sola familia, Public Sans Variable, autoalojada; jerarquía por peso y tamaño, no por cambio de familia.
- Neutros fríos teñidos hacia el petróleo; ningún gris puro.
- Superficies blancas con borde fino y sombra ambiental casi imperceptible.
- Estado = ícono lucide (trazo 2.25) + texto, sobre tinte del mismo tono.
- Piso WCAG 2.2 AA en cada par de color usado.

## Colors

Paleta institucional sobria: un petróleo profundo como voz, un azul de acción para lo navegable y una escala de neutros fríos que comparte el matiz del petróleo.

### Primary
- **Petróleo Institucional** (petroleo-institucional): el color del isotipo. Texto de los botones, `theme-color` del navegador y ancla de la escala de marca.
- **Petróleo Profundo** (petroleo-profundo): títulos de página (h1) y texto sobre selección; el petróleo en su registro de máxima autoridad.
- **Petróleo Medio** (petroleo-medio): borde del botón al pasar el puntero; el paso intermedio entre la línea neutra y la marca.
- **Velo Petróleo** (petroleo-velo): fondo de selección de texto y estado activo (presionado) del botón.
- **Bruma Petróleo** (petroleo-bruma): fondo de hover del botón y relleno de los esqueletos de carga.

### Secondary
- **Azul de Acción** (azul-accion): el azul del sitio institucional. Solo como anillo de foco (2px, separación 2px; 4.25:1 sobre lienzo).
- **Azul de Acción Profundo** (azul-accion-profundo): color de los enlaces (6.6:1). El azul es lo que se puede seguir; el petróleo es lo que la Caja afirma.

### Tertiary (estados)
- **Verde Conforme** (exito) sobre **Tinte Conforme** (exito-tinte): operativo, conciliado, correcto.
- **Ámbar Atención** (advertencia) sobre **Tinte Atención** (advertencia-tinte): degradado, pendiente de acción.
- **Rojo Rechazo** (peligro) sobre **Tinte Rechazo** (peligro-tinte): sin respuesta, rechazado, fallido.
- Cada par texto/tinte supera 5.5:1. Los tonos se usan siempre en pareja; nunca el texto de estado sobre otro fondo.

### Neutral
- **Tinta** (tinta): texto principal y valores (14.8:1).
- **Tinta Secundaria** (tinta-secundaria): etiquetas, descripciones, nombre de la Suite en la cabecera, pie de panel (6.4 a 6.9:1).
- **Tinta Tenue** (tinta-tenue): valores ausentes ("No disponible"); el piso legible (4.9:1), solo sobre superficie blanca o hundida.
- **Línea** (linea): bordes de panel, cabecera y divisores de filas.
- **Línea Firme** (linea-firme): borde de controles en reposo y color de la barra de desplazamiento.
- **Lienzo** (lienzo): fondo de la aplicación detrás de todo panel.
- **Superficie** (superficie): paneles, cabecera, botones.
- **Superficie Hundida** (superficie-hundida): pie de panel con metadatos y fondo del estado "desconocido".

### Named Rules
**La Regla del Sello.** El petróleo pertenece a lo que la Caja afirma (títulos, acciones, marca). Nunca decora fondos amplios ni rellena superficies de lectura.

**La Regla del Azul Navegable.** El azul de acción marca solo foco y enlaces. Si algo es azul, se puede seguir o tiene el foco.

**La Regla de la Pareja de Estado.** Cada tono de estado existe como par texto-700 sobre tinte-50; no se usan por separado ni se inventan tonos nuevos sin su par verificado AA.

## Typography

**Display Font:** Public Sans Variable (con ui-sans-serif, system-ui, sans-serif)
**Body Font:** Public Sans Variable (misma familia)

**Character:** Una grotesca de origen gubernamental, neutra y legible, que suena a documento oficial sin rigidez. La jerarquía se construye con peso (400, 500, 600) y tamaño; una sola familia en toda la Suite.

### Hierarchy
- **Headline** (600, 1.5rem, sube a 1.75rem desde 640px, tracking -0.025em): título de página (h1), en Petróleo Profundo.
- **Title** (600, 1.125rem, 1.556): título de panel o resumen de estado (h2), en Tinta.
- **Body** (400, 1rem, 1.5): párrafo introductorio y valores de fila; ancho máximo 65ch.
- **Body-sm** (400, 0.875rem): descripciones bajo un título y datos secundarios.
- **Label** (500, 0.875rem): etiquetas de fila (dt), nombre de la Suite en la cabecera; los botones y estados usan este tamaño en 600.
- **Caption** (400, 0.75rem): metadatos del pie de panel ("Última verificación").

### Named Rules
**La Regla de las Cifras Alineadas.** Toda hora, fecha, importe o cantidad se compone con cifras tabulares (`tabular-nums`) en el elemento que las contiene, para que los valores no bailen al refrescarse.

**La Regla del Peso Justo.** El techo de peso es 600. La jerarquía no recurre a 700+, mayúsculas sostenidas ni tracking abierto.

## Layout

Columna única centrada con ancho máximo de 64rem (1024px) compartida por cabecera y contenido, para que el logo y el título queden en el mismo eje. Márgenes laterales de 16px en celular y 24px desde 640px; el contenido principal respira 40px arriba y abajo (56px desde 640px). El ritmo sigue la base de 4px de Tailwind: 4, 8, 12, 16, 20, 24, 32, 40, 56.

Dentro de un panel, cada fila es un par etiqueta/valor con `justify-between` que se envuelve (`flex-wrap`) en pantallas angostas en vez de truncar; la cabecera del panel pasa de columna a fila desde 640px, con la acción alineada arriba. El único punto de quiebre en uso es 640px. Los objetivos táctiles miden al menos 44px de alto.

## Elevation & Depth

Sistema plano con una única sombra ambiental. Los paneles se separan del lienzo por el contraste blanco-sobre-gris frío y un borde fino; la sombra solo suaviza el canto, teñida con el petróleo de marca para no ensuciar. Dentro del panel la profundidad es tonal: la superficie hundida marca la franja de metadatos.

### Shadow Vocabulary
- **Panel ambiental** (`box-shadow: 0 1px 2px rgb(17 51 71 / 0.06), 0 2px 8px rgb(17 51 71 / 0.05)`): paneles de contenido en reposo. Es la única sombra del sistema.

### Named Rules
**La Regla del Canto Suave.** Una sola sombra, ambiental y teñida de petróleo. No hay sombras de hover, de elevación por capas ni sombras duras desplazadas.

## Shapes

Esquinas apenas redondeadas y funcionales: 6px en controles (botones, área clicable del logo) y 8px en paneles, de modo que el contenedor siempre sea un punto más suave que lo que contiene. La píldora completa queda reservada a los indicadores de estado, que así se distinguen de cualquier control. Bordes de 1px en todo; los paneles recortan su contenido (`overflow: hidden`) para que la franja hundida del pie siga la curva.

## Components

### Buttons
Contenidos y seguros: la acción se ofrece, no grita.
- **Shape:** esquinas suaves (6px), alto mínimo 44px.
- **Secundario (contorno), único en uso:** fondo Superficie, borde 1px Línea Firme, texto Petróleo Institucional en 0.875rem/600, padding horizontal 16px, ícono lucide de 16px (trazo 2.25) con separación de 8px.
- **Hover / Active:** el borde pasa a Petróleo Medio y el fondo a Bruma Petróleo; presionado, Velo Petróleo. Transición de color de 150ms con `cubic-bezier(0.22, 1, 0.36, 1)`.
- **Focus:** anillo global de 2px en Azul de Acción con separación de 2px.
- **Disabled / en curso:** opacidad 0.6, cursor de progreso, el ícono gira y el texto cambia a gerundio ("Verificando…").
- **Primario (relleno), Fase 1:** fondo Petróleo Institucional, texto blanco 0.875rem/600; hover Petróleo Medio, presionado Petróleo Profundo. Uno por vista: la acción que la Caja afirma (Ingresar, Guardar, Crear y enviar correo).
- **Peligro (contorno):** como el secundario pero con texto Rojo Rechazo; hover con borde Rojo Rechazo y fondo Tinte Rechazo. Solo para acciones que quitan acceso (Suspender, Desactivar 2FA).
- **Fantasma:** sin borde ni fondo, texto Petróleo Institucional, hover Bruma Petróleo. Acciones por fila en grillas.

### Chips (indicador de estado)
- **Style:** píldora con ícono lucide de 16px (trazo 2.25) y texto 0.875rem/600, padding 4px 12px 4px 8px, separación 6px; texto y tinte del mismo tono.
- **State:** conforme (CircleCheck), atención (TriangleAlert), rechazo (CircleX), desconocido (CircleDashed, Tinta Secundaria sobre Superficie Hundida). El ícono es `aria-hidden`; la palabra lleva el significado.

### Cards / Containers (panel)
- **Corner Style:** 8px.
- **Background:** Superficie; pie de metadatos en Superficie Hundida.
- **Shadow Strategy:** Panel ambiental (ver Elevation & Depth).
- **Border:** 1px Línea; secciones internas y filas divididas por 1px Línea.
- **Internal Padding:** 20px horizontal en celular, 24px desde 640px; filas 16px vertical, cabecera 20px, pie 12px.
- **Carga:** esqueletos en Bruma Petróleo con pulso, del alto del contenido final, dentro de una región `aria-live="polite"` con `aria-busy`.

### Inputs (campos de formulario)
- Etiqueta arriba (Label 0.875rem/500 en Tinta), campo de 44px de alto mínimo, borde 1px Línea Firme, esquinas 6px, texto 1rem en Tinta.
- Foco: borde Azul de Acción más el anillo global. Error: borde y mensaje en Rojo Rechazo debajo, enlazado con `aria-describedby`; la ayuda va en Tinta Secundaria.
- Contraseña con botón de mostrar/ocultar de 40px dentro del campo. Códigos (TOTP, recuperación) con cifras tabulares y tracking abierto; `autocomplete="one-time-code"`.
- Requisitos de contraseña como lista viva: ícono de check en Verde Conforme o círculo en Tinta Secundaria, con texto para lector de pantalla.

### Alerts (avisos en línea)
- Caja de 6px con borde del tono al 25%, fondo Tinte y texto del tono; ícono lucide de 20px (trazo 2.25) a la izquierda, título opcional en 600.
- Tonos: conforme, atención, rechazo (con `role="alert"`) e informativo en Bruma Petróleo con texto Petróleo Institucional.

### Dialog (modal)
- `<dialog>` nativo con `showModal`: foco atrapado, Escape y fondo inerte del navegador; al abrir, el foco va al primer campo.
- Panel de 8px, ancho máximo 32rem, cabecera con título y botón de cerrar de 44px, pie en Superficie Hundida con acciones a la derecha (apiladas en celular, la principal arriba). Fondo del backdrop: Petróleo 950 al 40%.
- Solo para tareas que necesitan foco protegido: alta, suspensión con motivo, roles, códigos 2FA.

### Tables y listas de datos
- Tabla dentro del panel, cabecera fija (`sticky`) en Superficie Hundida con texto Caption/600 en Tinta Secundaria; filas divididas por Línea; cifras tabulares en CUIT y fechas.
- Paginación en servidor en el pie del panel: rango "1–20 de 57" y botones de 44px.
- Bajo 640px la tabla se reemplaza por una lista apilada (nombre, estado a la derecha, pares etiqueta/valor y acciones), sin scroll horizontal.
- Esqueletos en Bruma Petróleo mientras carga; estado vacío que explica qué buscar.

### Navigation (cabecera institucional)
- Barra de 72px sobre Superficie con borde inferior Línea. Logo oficial a la izquierda (36px de alto, 44px desde 640px), enlazado al inicio. Mismo ancho máximo que el contenido.
- Pública (ingreso, recuperación): a la derecha, "Suite Notarial" en Label y Tinta Secundaria; el formulario va en una columna de 28rem.
- Autenticada: a la derecha, nombre de la persona con "Seguridad de la cuenta" debajo y "Cerrar sesión"; debajo, fila de navegación con las secciones que el usuario puede ver (la activa sobre Bruma Petróleo). En celular, un botón de menú despliega la navegación.
- Si el rol exige 2FA y falta activarlo, la navegación se oculta: solo existe Seguridad de la cuenta.

## Do's and Don'ts

### Do:
- **Do** declarar todo estado con ícono lucide (trazo 2.25) y texto; el color acompaña, nunca porta el significado solo.
- **Do** usar los pares de estado completos (texto-700 sobre tinte-50) y verificar AA (4.5:1) ante cualquier tono nuevo.
- **Do** componer horas, fechas e importes con cifras tabulares.
- **Do** mantener la columna de 64rem compartida entre cabecera y contenido, con márgenes de 16px y 24px.
- **Do** cambiar identidad solo vía tokens de `@theme` en `frontend/src/index.css`.
- **Do** dar a cada control un alto mínimo de 44px y conservar el anillo de foco global de Azul de Acción.

### Don't:
- **Don't** usar el Azul de Acción para rellenos, títulos o decoración; es foco y enlace.
- **Don't** sumar sombras más allá del Panel ambiental ni elevar en hover.
- **Don't** usar Tinta Tenue sobre tintes de estado o sobre el lienzo; solo sobre superficie blanca o hundida.
- **Don't** superar el peso 600 ni introducir una segunda familia tipográfica.
- **Don't** usar grises puros: todo neutro nuevo se tiñe hacia el petróleo.
- **Don't** redibujar, recolorear o reemplazar el logo oficial; se usa el archivo provisto tal cual.
