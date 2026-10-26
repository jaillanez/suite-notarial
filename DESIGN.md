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

- **Área de texto:** misma etiqueta, borde y foco que el campo; 3 filas por defecto. Para motivos obligatorios (cambios de estado, cierres), con la regla en la ayuda.
- **Fechas:** `<input type="date">` nativo; se muestran como dd/mm/aaaa con cifras tabulares y sin corrimiento de zona (fecha calendario).

### Alerts (avisos en línea)
- Caja de 6px con borde del tono al 25%, fondo Tinte y texto del tono; ícono lucide de 20px (trazo 2.25) a la izquierda, título opcional en 600.
- Tonos: conforme, atención, rechazo (con `role="alert"`) e informativo en Bruma Petróleo con texto Petróleo Institucional.

### Dialog (modal)
- `<dialog>` nativo con `showModal`: foco atrapado, Escape y fondo inerte del navegador; al abrir, el foco va al primer campo.
- Panel de 8px, ancho máximo 32rem, cabecera con título y botón de cerrar de 44px, pie en Superficie Hundida con acciones a la derecha (apiladas en celular, la principal arriba). Fondo del backdrop: Petróleo 950 al 40%.
- Solo para tareas que necesitan foco protegido: alta, suspensión con motivo, roles, códigos 2FA.
- Alto máximo de la pantalla menos 2rem: si el contenido es largo, se desplaza solo el cuerpo; título y acciones quedan siempre visibles.

### Tables y listas de datos
- Tabla dentro del panel, cabecera fija (`sticky`) en Superficie Hundida con texto Caption/600 en Tinta Secundaria; filas divididas por Línea; cifras tabulares en CUIT y fechas.
- Paginación en servidor en el pie del panel: rango "1–20 de 57" y botones de 44px.
- Bajo 640px la tabla se reemplaza por una lista apilada (nombre, estado a la derecha, pares etiqueta/valor y acciones), sin scroll horizontal.
- Esqueletos en Bruma Petróleo mientras carga; estado vacío que explica qué buscar.

### Fichas (detalle de una entidad)
- Volver como enlace con flecha arriba a la izquierda; título en Headline con la identidad (nombre, número) y debajo los identificadores en cifras tabulares más el indicador de estado. Las acciones van a la derecha del título, en botones secundarios; las que quitan algo, en peligro.
- Cuerpo en paneles: pares etiqueta/valor (valor a la derecha) en dos columnas desde 1024px; listas de historial con lo más reciente arriba.
- Un historial de estados muestra estado anterior → nuevo con sus indicadores, el motivo en Body y una línea Caption con resolución, fecha y operador.

### Listas navegables
- Cuando cada fila lleva a una ficha, la fila entera es el enlace (hover en Bruma Petróleo y chevron a la derecha). Un número identificador grande y tabular (p. ej. el Nº de registro) puede encabezar la fila.

### Importes y tasas
- Los importes y porcentajes llegan de la API como texto decimal y se formatean sin pasar por número de punto flotante: `$ 1.234.567,50`, `1,5 %` (sin ceros de más). Siempre con cifras tabulares.
- Los campos de importe aceptan la forma local (`1.234,56`) y se normalizan antes de enviarse.
- Un valor que no está confirmado como oficial lleva el indicador de atención "A confirmar" junto al valor y un aviso en la página; nunca se presenta igual que uno aprobado.

### Liquidación (desglose de importes)
- Lista de pares etiqueta/valor con el importe alineado a la derecha y sin cortes de línea; la aclaración de una fila (cantidad de aportes, días de mora) va junto a la etiqueta en escritorio y debajo en celular.
- Los subtotales van sobre Superficie Hundida en 600; el total a pagar cierra la lista con borde Línea Firme, en Petróleo Profundo y un paso más grande.
- Una vista previa que se recalcula conserva los importes anteriores atenuados mientras llega el nuevo resultado: el panel no salta ni se vacía.
- Si el cálculo usa un parámetro marcado como ejemplo, un aviso de atención lo dice antes de presentar y en la confirmación.

### Carga de archivos
- Zona de archivo como etiqueta del `<input type="file">` (oculto para la vista, accesible): borde punteado Línea Firme sobre Superficie Hundida, ícono de 24px y dos líneas (acción y formatos admitidos); elegido el archivo, muestra nombre y tamaño. Foco y hover como un control.
- Cuando cargar algo no completa el trámite (comprobante ≠ pago), un aviso informativo lo dice antes del botón de envío.

### Revisión de comprobantes (Tesorería)
- Dos columnas desde 1024px: visor del archivo (PDF en marco, imagen contenida) a la izquierda y el cotejo con la boleta a la derecha; en celular, apilados.
- La fila de diferencia es la única con tinte: conforme si coincide, atención con el importe si no.
- Las acciones van debajo, una por panel: confirmar (primario, con diálogo de confirmación que repite los importes) y rechazar (peligro, motivo obligatorio). Los motivos frecuentes son botones fantasma con borde que completan el campo; el elegido queda marcado.
- Los importes que verifica Tesorería nunca se precargan con lo declarado.

### Reportes
- Filtros en grilla de hasta cuatro columnas arriba de la tabla; se aplican al cambiar y ofrecen «Quitar filtros».
- «Columnas (n de m)» despliega casillas para elegir las columnas visibles; la exportación siempre incluye todas. La elección se recuerda en el navegador.
- Tabla dentro de un área con alto máximo: cabecera fija arriba y fila de totales fija abajo (Superficie Hundida, 600, con «Total · n filas»). Si se eligen muchas columnas, el desplazamiento horizontal queda acotado al panel.
- Exportar a Excel y CSV como botones secundarios en la cabecera del panel; el pie recuerda que cada exportación queda auditada y si el reporte tiene datos sensibles.

### Sitio institucional (público)
- Misma identidad que la Suite, en modo lectura: cabecera con logo y navegación corta (Inicio, Novedades, Verificar boleta, Ingresar), columna de 64rem y pie con la nota de integridad.
- Secciones separadas por una línea fina y un título en Petróleo Profundo, sin tarjetas: la información se lee como un registro.
- Documentos agrupados por tipo; el ejercicio encabeza cada fila en cifras grandes y tabulares, con «Descargar PDF» como botón secundario. Huella y versiones anteriores en un desplegable con chevron.
- Novedades en una columna de 65ch, cuerpo en 1.125rem y párrafos separados; el texto se muestra tal cual se cargó (escapado).

### Cuadro de amortización
- Tabla de cuotas con cabecera y totales fijos (capital, intereses y total), cifras tabulares y la cuota en 600; en celular, una tarjeta por cuota. En préstamos vigentes, una columna de estado (pagada, pendiente, vencida) y la fila vencida con tinte de rechazo.
- Las evaluaciones muestran primero el veredicto (cumple / no se puede otorgar con sus motivos), después cuota, tasa, afectación contra el tope (con tinte de rechazo si lo supera) y total a devolver.
- Los importes que se tipean aceptan puntos de miles ("1.500.000"); las tasas, coma decimal.

### Revisión asistida (IA)
- Página propia, no diálogo: arriba un aviso informativo («Vos confirmás cada dato»); debajo, dos columnas desde 1024px. A la izquierda, «Lo que leyó la Suite»: alertas (atención primero) y cada dato con su valor, la regla aplicada, la confianza y el fragmento del documento en una cita sobre Superficie con borde Línea. A la derecha, el mismo formulario de la carga manual.
- Debajo de cada campo, una pista con ícono y texto: «Sugerido por la Suite, confianza alta (95 %).» (destellos), «Corregido. La Suite había sugerido 345.» (lápiz) o «La Suite no lo encontró en el documento: completalo.» (círculo punteado). Con confianza baja, la pista va en Ámbar Atención con «verificalo». Nunca se preselecciona un dato que la Suite no encontró.
- La acción principal («Confirmar y agregar el acto», «Dar de alta») queda deshabilitada hasta tildar «Revisé los datos…»; cambiar cualquier campo destilda la casilla. «Descartar» es secundario.
- En un formulario existente (alta de escribano), la lectura es un panel opcional al principio, con la zona de archivo y, leído el documento, sus avisos y «Descartar la lectura».

### Migración (cuadratura y conformidad)
- Lista de corridas como lista navegable: modo y fecha a la izquierda; «Cuadra» o «No cuadra» y el estado a la derecha, como indicadores; debajo, bloqueantes, advertencias y qué área firmó.
- La ficha abre con el veredicto como aviso con título («Cuadra al centavo», o «No cuadra» con la lista de causas en palabras), seguido de la tabla de cuadratura (control, leídas, cargadas y rechazadas; importes aparte) con la fila que no cuadra en Tinte Rechazo. En celular, una tarjeta por archivo.
- Observaciones con filtros de severidad y archivo, paginadas en el servidor; cada una con su indicador (bloqueante en rechazo, advertencia en atención), el mensaje y, debajo, archivo, línea y código del origen. Arriba, el conteo por código como píldoras neutras.
- La tabla de homologación se muestra en desplegables por tabla (código del origen en monoespaciada → valor de la Suite): es parte de lo que se firma.
- La conformidad es un panel con una fila por área (pendiente o «Firmó …» con fecha). El formulario aparece solo para quien puede firmar: casilla «Revisé la cuadratura y las observaciones…» y botón primario «Firmar conformidad de …». Lo que falta para la carga definitiva se lista con el ícono de pendiente; nunca con un tilde.

### Verificación pública
- Página de lectura en la cabecera pública: campo de código (acepta espacios, guiones y minúsculas) y el veredicto como aviso con título ("Boleta auténtica" o rechazo), seguido de la ficha mínima de la boleta. Nunca muestra datos personales.

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
