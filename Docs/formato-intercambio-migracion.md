# Formato de intercambio para la migración (versión 2)

Lo que la extracción del sistema anterior tiene que entregar para que la Suite lo valide, lo cargue y lo cuadre. El sistema anterior todavía no fue auditado (decisión D-03 del módulo 11), así que el formato lo fija la Suite y la extracción se escribe para producirlo.

## Cambios de la versión 2

El listado del sistema anterior trae escribanos sin matrícula (unos 40 activos y muchos históricos), sin fecha de juramento (antes «fecha de matriculación»), y personas históricas (fallecidos, jubilados, renunciados) sin CUIT ni documento. Nadie queda afuera del padrón: se cargan con esos datos vacíos y la ficha los muestra «a completar»; la Caja los carga después, una sola vez y con auditoría, desde la ficha del escribano.

- `escribanos.csv`: `cuit`, `numero_documento`, `matricula` y `fecha_matriculacion` (fecha de juramento) pasan a ser **opcionales**. Vacíos se cargan como nulos. Si vienen, se validan (CUIT por Módulo 11 y único, matrícula entera positiva, fecha legible). La matrícula **no es única** (ver abajo).
- `cargos.csv`: la columna `matricula` se reemplaza por **`escribano`**, el `codigo_legado` del escribano en `escribanos.csv`.
- **Los lotes v1 ya no se aceptan:** un `cargos.csv` con `matricula` y sin `escribano` se rechaza al leer el lote con un mensaje que lo indica. Convertirlo es directo (cambiar la matrícula por el código del escribano), y aceptar los dos formatos dejaría dos claves posibles para el mismo vínculo.

**TODO(negocio):** tras la auditoría del origen, confirmar con la Caja qué datos y qué períodos se trasladan y qué columnas no existen en el sistema anterior.

### Agregado: créditos a favor del escribano (`creditos.csv`)

En el libro de pagos del sistema anterior los importes negativos son **créditos a favor del escribano**, casi todos «diferencias de inspección» (la inspección encontró que había pagado de más). Hasta ahora no tenían lugar en el formato (las boletas no admiten importes negativos y los pagos tienen que ser mayores que cero) y esas filas se rechazaban.

El formato sigue siendo la **versión 2**: se agrega un archivo **opcional**, `creditos.csv`, con el importe **en positivo**. Un lote sin ese archivo se lee igual que antes (misma huella). Si el archivo viene, `control.csv` tiene que traer la fila `creditos`; si `control.csv` la trae, el archivo tiene que venir.

**TODO(negocio):** decidir si el saldo a favor del sistema anterior compensa deuda (préstamos, garantes, boletas nuevas). Por ahora solo resta del saldo histórico del registro (cuadratura y reportes); no habilita préstamos ni garantes.

### Ajustes de la Caja tras revisar el padrón (compatibles con la versión 2)

Decisiones de la Caja, sin cambiar de versión (un lote anterior se sigue leyendo igual):

- **La matrícula no identifica al escribano.** El Colegio puede reasignar el número de un escribano retirado a uno nuevo. Ya no se controla que sea única ni en el archivo ni contra la Suite: es un dato informativo. Identifica el **CUIT** (único cuando viene).
- **«Fecha de matriculación» pasa a llamarse «fecha de juramento».** La columna conserva su nombre, `fecha_matriculacion`.
- `registros.csv`: **`circunscripcion` pasa a ser opcional.** Vacía o ausente, el registro va a la circunscripción **«San Juan»** (la Caja tiene una sola).
- `escribanos.csv`: se agregan, **opcionales**, los datos de la **primera escritura** autorizada (determina la antigüedad para la jubilación): `primera_escritura_fecha`, `primera_escritura_numero`, `primera_escritura_registro`, `primera_escritura_folio`.
- **Nuevo archivo opcional `licencias.csv`:** licencias del escribano (deja de ejercer un tiempo y vuelve; su cargo sigue siendo suyo). Como con `creditos.csv`: si viene, `control.csv` trae la fila `licencias`, y si `control.csv` la trae, el archivo tiene que venir. Sin el archivo, la huella del lote no cambia.
- Al cargar, cada registro abre su **historia de domicilios** con el domicilio del lote, vigente desde `fecha_creacion` (o desde el día de la corrida si no viene).

## El lote

Un directorio con seis archivos CSV (más los opcionales de créditos y licencias):

| Archivo | Contenido |
|---------|-----------|
| `registros.csv` | Registros notariales |
| `escribanos.csv` | Personas y matrículas |
| `cargos.csv` | Titulares, adscriptos y a cargo de cada registro (vigentes e históricos) |
| `licencias.csv` | **Opcional.** Licencias de los escribanos (vigentes y terminadas) |
| `boletas.csv` | Boletas emitidas por el sistema anterior |
| `pagos.csv` | Pagos aplicados a esas boletas |
| `creditos.csv` | **Opcional.** Créditos a favor del escribano (importes negativos del origen, en positivo) |
| `control.csv` | Totales que declara el sistema anterior (el «origen» de la cuadratura) |

- **Codificación:** UTF-8 (con o sin BOM) o Windows-1252. Se detecta y queda en el informe.
- **Separador:** `;`, `,` o tabulador (se toma el más frecuente del encabezado).
- **Encabezado obligatorio.** Los nombres de columna no distinguen mayúsculas; las columnas extra se ignoran.
- **Máximo:** 500.000 filas por archivo.
- Cada fila lleva un `codigo_legado` único en su archivo: es el identificador del sistema anterior y queda en el mapeo origen → Suite.

## Valores

| Tipo | Formatos aceptados | Notas |
|------|--------------------|-------|
| Fecha | `aaaa-mm-dd`, `dd/mm/aaaa`, `dd-mm-aaaa` (la hora, si viene, se descarta) | Fechas inexistentes se rechazan |
| Período | `aaaa-mm`, `mm/aaaa`, `aaaamm` | |
| Importe | `1.234,50`, `1234,5`, `1234.50`, `1,234.50`, `$ 1.234` | **Nunca se redondea.** Más de dos decimales distintos de cero (típico de un `float` del origen) se rechaza |
| Entero | Solo dígitos | Matrícula (mayor que cero, puede repetirse), número de registro |
| CUIT | 11 dígitos con o sin guiones | Se valida el dígito verificador (Módulo 11) |

## Columnas

Obligatorias en **negrita**.

### registros.csv
**codigo_legado**, **numero_registro**, circunscripcion (nombre; se crea si no existe; vacía = «San Juan»), **departamento** (uno de los 19 de San Juan, sin importar tildes ni mayúsculas; vacío = «a completar»: la columna va, el valor puede faltar), **domicilio_legal**, **estado** (código del origen, se homologa), nombre_fantasia, fecha_creacion.

### escribanos.csv
**codigo_legado**, **apellido**, **nombre**, **estado** (se homologa), cuit, tipo_documento (DNI, LC, LE o PASAPORTE; por defecto DNI), numero_documento, matricula, fecha_matriculacion (fecha de juramento), fecha_nacimiento, email, primera_escritura_fecha, primera_escritura_numero (texto, hasta 20), primera_escritura_registro (número de registro; puede ser uno que ya no existe), primera_escritura_folio (texto, hasta 20).

`cuit`, `numero_documento`, `matricula` y `fecha_matriculacion` vacíos se cargan como nulos («a completar»). Varios escribanos sin CUIT no chocan entre sí: la unicidad del CUIT aplica solo a los valores cargados. La matrícula puede repetirse (matrícula reasignada).

La primera escritura va **completa** (fecha, número y registro; el folio es opcional) o vacía. Si viene incompleta o con un valor ilegible, el escribano **se carga igual** sin primera escritura (queda «a completar») y la fila queda con una advertencia; también se advierte si es anterior a la fecha de juramento.

### cargos.csv
**codigo_legado**, **escribano** (el `codigo_legado` del escribano), **numero_registro**, **cargo** (se homologa: titular, adscripto o a cargo), **fecha_desde**, fecha_hasta (vacía = vigente).

`fecha_desde` vacía se carga nula («a completar») con una advertencia: mientras falte, el cargo cuenta desde antes de todo lo migrado (integra el equipo del registro en cualquier período anterior a su cierre). La Caja la carga después, una sola vez, desde la ficha del escribano («Cargar fecha desde»). El carácter (`cargo`) no se puede dejar vacío.

### licencias.csv (opcional)
**codigo_legado**, **escribano** (el `codigo_legado` del escribano), **fecha_desde**, fecha_hasta (vacía = vigente, sin fecha de regreso), motivo (texto; vacío = «Migrada del sistema anterior»).

Una licencia no cambia el estado de la matrícula ni cierra el cargo del escribano. Si el escribano no se puede cargar, la licencia tampoco (en cascada). Dos licencias del mismo escribano que se superponen se observan las dos. Una licencia **vigente** de un escribano cesante, jubilado o fallecido se rechaza (falta la fecha de regreso); una ya terminada se carga como historia.

```
codigo_legado;escribano;fecha_desde;fecha_hasta;motivo
LIC-12;ESC-20111111112;10/01/2008;30/06/2008;Licencia por estudios
LIC-40;ESC-27222222228;01/08/2025;;
```

### boletas.csv
**codigo_legado**, **numero_registro**, **periodo**, **fecha_emision**, **fecha_vencimiento**, **importe**, **estado** (se homologa: impaga, pagada o anulada), numero_boleta, escribano_origen.

`escribano_origen` es el nombre de quien pagó tal como figura en el origen. Con él, `numero_registro` puede venir vacío: la boleta se carga igual, con una advertencia (`REGISTRO_A_COMPLETAR`), y la Caja le asigna el registro después desde «Migración» → «Boletas sin registro» (por escribano y por meses; una sola vez por boleta, auditado: es el único cambio que admite el histórico). Sin registro ni nombre, la boleta se rechaza.

### pagos.csv
**codigo_legado**, **boleta** (el `codigo_legado` de la boleta), **fecha_pago**, **importe**, medio.

### creditos.csv (opcional)
**codigo_legado**, **numero_registro**, **fecha** (del crédito), **importe** (en positivo: lo que el sistema anterior le debe al escribano), periodo (`aaaa-mm` u otro formato de período: el mes al que se refiere), concepto (texto, hasta 100 caracteres).

El importe sigue las mismas reglas que el resto: nunca se redondea y más de dos decimales se rechaza. Tiene que ser **mayor que cero** (un crédito negativo o en cero se rechaza). El registro tiene que poder cargarse: si el registro se rechaza, el crédito también (en cascada, como las boletas).

```
codigo_legado;numero_registro;fecha;importe;periodo;concepto
CRE-1043;701;15/05/2026;1037,01;05/2026;Diferencia de inspección
```

### control.csv
Columnas `entidad;filas;importe`, una fila por archivo (`registros`, `escribanos`, `cargos`, `boletas`, `pagos` y, si el lote los trae, `licencias` y `creditos`). `importe` es obligatorio para boletas, pagos y créditos: la suma que informa el sistema anterior (los créditos, en positivo).

```
entidad;filas;importe
registros;150;
escribanos;222;
cargos;222;
licencias;2;
boletas;36000;5245873210,55
pagos;34621;4180032117,10
creditos;12;84210,30
```

(Las cifras del ejemplo son ilustrativas.)

Columna opcional `ajuste_redondeo`: si la extracción redondeó importes del origen al centavo (p. ej. un `float` de Excel como 18618,0744), declara por entidad la suma **exacta** de (redondeado − origen) de esas filas, con el detalle fila por fila en `redondeos.csv`. La cuadratura exige entonces `importe` = leído − ajuste, redondeado al centavo, y el informe muestra el ajuste. No es una tolerancia: un ajuste que no explica exactamente la diferencia no cuadra.

## Homologación

Un JSON con cuatro tablas que traducen los códigos del origen a los valores de la Suite: `estado_escribano`, `estado_registro`, `cargo` y `estado_boleta`. La de ejemplo está en `backend/app/modules/migracion/homologacion_ejemplo.json`.

- Un código que no está en la tabla no se adivina: la fila queda observada y no se carga.
- La tabla de ejemplo se reconoce por su contenido aunque se le quite la marca `es_ejemplo`: con ella no se puede hacer la carga definitiva.
- Cada corrida guarda la huella y el contenido de su tabla. La conformidad de Tesorería y Caja cubre **el lote y la tabla**: la carga definitiva exige los dos iguales a los del simulacro firmado.

## Qué se valida

| Regla | Si falla |
|-------|----------|
| Columnas obligatorias y `codigo_legado` | Bloqueante |
| Códigos, CUIT y números de registro únicos en el archivo (los vacíos no cuentan). La matrícula **no** se controla: puede repetirse | Bloqueante (todas las filas en conflicto, no se elige una) |
| CUIT o registro que ya existen en la Suite | Bloqueante |
| Fechas, períodos e importes legibles | Bloqueante |
| Códigos homologados | Bloqueante |
| Un cargo vigente por escribano (por su `codigo_legado`) y un titular vigente por registro | Bloqueante |
| Cargo o licencia vigente de un escribano cesante, jubilado o fallecido | Bloqueante |
| Licencias superpuestas del mismo escribano | Bloqueante (todas las filas en conflicto) |
| Referencias (cargo → escribano y registro, licencia → escribano, boleta → registro, pago → boleta, crédito → registro) | Bloqueante, en cascada: si una fila no se carga, tampoco las que dependen de ella |
| Importe de un crédito en cero o negativo | Bloqueante |
| DNI distinto del incluido en el CUIT (solo si vienen los dos), correo inválido, registro activo sin titular, vencimiento anterior a la emisión, pagos de boletas anuladas, pagos que no coinciden con el estado de la boleta, pagos o créditos con fecha posterior al día de la corrida, licencia o primera escritura anterior a la fecha de juramento, primera escritura incompleta o ilegible (el escribano se carga sin ella) | Advertencia: la fila se carga y queda para revisar |

Las observaciones identifican la fila (línea del archivo) y su `codigo_legado`; no repiten datos personales.

## Cuadratura

Para cada archivo, la corrida cuadra cuando:

1. **control = leído:** el lote trae todas las filas e importes que declara el sistema anterior;
2. **leído = cargado + rechazado:** toda fila no cargada tiene su observación bloqueante;
3. el saldo de cada registro (boletas no anuladas menos pagos menos créditos) es el mismo en origen y destino. Un saldo negativo es un **saldo a favor** del escribano; el informe muestra cuántos registros quedan a favor y cuánto suman.

Si el lote no trae `creditos.csv` o `licencias.csv`, esa entidad no figura en el informe. Las licencias cuadran por filas (no tienen importe).

Lo cargado se consulta a la base, no se toma de memoria. Ninguna diferencia se compensa: si algo no cuadra, el informe muestra cuánto y por qué.

## Dónde va cada cosa

- **Padrón** (registros y su domicilio vigente, personas, escribanos con su primera escritura, cargos y licencias): a las tablas operativas de la Suite. Lo que vino vacío queda «a completar» en la ficha; sin CUIT no se le puede crear la cuenta de autogestión hasta completarlo.
- **Boletas y pagos:** a `historico_boletas` e `historico_pagos`, de solo lectura. No se convierten en boletas de la Suite, porque no tienen vigencia paramétrica ni conciliación y serían asientos ficticios. Cuentan como deuda (p. ej. para garantes de préstamos) y se consultan en el reporte «Boletas del sistema anterior».
- **Créditos:** a `historico_creditos`, de solo lectura, y se consultan en el reporte «Créditos del sistema anterior». No se imputan a ninguna boleta: restan del saldo del registro.
- **Deuda para préstamos (garantes), fail-closed:** se calcula boleta por boleta. Cada boleta no anulada y vencida a la fecha de la evaluación debe su importe menos sus propios pagos con fecha hasta ese día (nunca menos de cero); un registro debe si esa suma es positiva. Lo pagado de más en una boleta no compensa otra, un pago con fecha posterior no cuenta y **los créditos a favor no reducen esta deuda**: siguen en el saldo de la cuadratura y en los reportes, pero no habilitan a nadie.

**TODO(negocio):** decidir si el saldo a favor del sistema anterior compensa deuda (préstamos, garantes, boletas nuevas).

**TODO(negocio):** si la Caja necesita el detalle de actos de las DDJJ históricas, se agrega un archivo al formato (en una versión posterior).
