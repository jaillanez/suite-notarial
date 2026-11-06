# Formato de intercambio para la migración (versión 2)

Lo que la extracción del sistema anterior tiene que entregar para que la Suite lo valide, lo cargue y lo cuadre. El sistema anterior todavía no fue auditado (decisión D-03 del módulo 11), así que el formato lo fija la Suite y la extracción se escribe para producirlo.

## Cambios de la versión 2

El listado del sistema anterior trae escribanos sin matrícula (unos 40 activos y muchos históricos), sin fecha de matriculación, y personas históricas (fallecidos, jubilados, renunciados) sin CUIT ni documento. Nadie queda afuera del padrón: se cargan con esos datos vacíos y la ficha los muestra «a completar»; la Caja los carga después, una sola vez y con auditoría, desde la ficha del escribano.

- `escribanos.csv`: `cuit`, `numero_documento`, `matricula` y `fecha_matriculacion` pasan a ser **opcionales**. Vacíos se cargan como nulos. Si vienen, se validan como antes (CUIT por Módulo 11 y único, matrícula entera positiva y única, fecha legible).
- `cargos.csv`: la columna `matricula` se reemplaza por **`escribano`**, el `codigo_legado` del escribano en `escribanos.csv`.
- **Los lotes v1 ya no se aceptan:** un `cargos.csv` con `matricula` y sin `escribano` se rechaza al leer el lote con un mensaje que lo indica. Convertirlo es directo (cambiar la matrícula por el código del escribano), y aceptar los dos formatos dejaría dos claves posibles para el mismo vínculo.

**TODO(negocio):** tras la auditoría del origen, confirmar con la Caja qué datos y qué períodos se trasladan y qué columnas no existen en el sistema anterior.

### Agregado: créditos a favor del escribano (`creditos.csv`)

En el libro de pagos del sistema anterior los importes negativos son **créditos a favor del escribano**, casi todos «diferencias de inspección» (la inspección encontró que había pagado de más). Hasta ahora no tenían lugar en el formato (las boletas no admiten importes negativos y los pagos tienen que ser mayores que cero) y esas filas se rechazaban.

El formato sigue siendo la **versión 2**: se agrega un archivo **opcional**, `creditos.csv`, con el importe **en positivo**. Un lote sin ese archivo se lee igual que antes (misma huella). Si el archivo viene, `control.csv` tiene que traer la fila `creditos`; si `control.csv` la trae, el archivo tiene que venir.

**TODO(negocio):** decidir si el saldo a favor del sistema anterior compensa deuda (préstamos, garantes, boletas nuevas). Por ahora solo resta del saldo histórico del registro (cuadratura y reportes); no habilita préstamos ni garantes.

## El lote

Un directorio con seis archivos CSV (siete si trae créditos):

| Archivo | Contenido |
|---------|-----------|
| `registros.csv` | Registros notariales |
| `escribanos.csv` | Personas y matrículas |
| `cargos.csv` | Titulares, adscriptos y a cargo de cada registro (vigentes e históricos) |
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
| Entero | Solo dígitos | Matrícula (mayor que cero), número de registro |
| CUIT | 11 dígitos con o sin guiones | Se valida el dígito verificador (Módulo 11) |

## Columnas

Obligatorias en **negrita**.

### registros.csv
**codigo_legado**, **numero_registro**, **circunscripcion** (nombre; se crea si no existe), **departamento** (uno de los 19 de San Juan, sin importar tildes ni mayúsculas), **domicilio_legal**, **estado** (código del origen, se homologa), nombre_fantasia, fecha_creacion.

### escribanos.csv
**codigo_legado**, **apellido**, **nombre**, **estado** (se homologa), cuit, tipo_documento (DNI, LC, LE o PASAPORTE; por defecto DNI), numero_documento, matricula, fecha_matriculacion, fecha_nacimiento, email.

`cuit`, `numero_documento`, `matricula` y `fecha_matriculacion` vacíos se cargan como nulos («a completar»). Varios escribanos sin matrícula o sin CUIT no chocan entre sí: la unicidad aplica solo a los valores cargados.

### cargos.csv
**codigo_legado**, **escribano** (el `codigo_legado` del escribano), **numero_registro**, **cargo** (se homologa: titular, adscripto o a cargo), **fecha_desde**, fecha_hasta (vacía = vigente).

### boletas.csv
**codigo_legado**, **numero_registro**, **periodo**, **fecha_emision**, **fecha_vencimiento**, **importe**, **estado** (se homologa: impaga, pagada o anulada), numero_boleta.

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
Columnas `entidad;filas;importe`, una fila por archivo (`registros`, `escribanos`, `cargos`, `boletas`, `pagos` y, si el lote trae `creditos.csv`, `creditos`). `importe` es obligatorio para boletas, pagos y créditos: la suma que informa el sistema anterior (los créditos, en positivo).

```
entidad;filas;importe
registros;150;
escribanos;222;
cargos;222;
boletas;36000;5245873210,55
pagos;34621;4180032117,10
creditos;12;84210,30
```

(Las cifras del ejemplo son ilustrativas.)

## Homologación

Un JSON con cuatro tablas que traducen los códigos del origen a los valores de la Suite: `estado_escribano`, `estado_registro`, `cargo` y `estado_boleta`. La de ejemplo está en `backend/app/modules/migracion/homologacion_ejemplo.json`.

- Un código que no está en la tabla no se adivina: la fila queda observada y no se carga.
- La tabla de ejemplo se reconoce por su contenido aunque se le quite la marca `es_ejemplo`: con ella no se puede hacer la carga definitiva.
- Cada corrida guarda la huella y el contenido de su tabla. La conformidad de Tesorería y Caja cubre **el lote y la tabla**: la carga definitiva exige los dos iguales a los del simulacro firmado.

## Qué se valida

| Regla | Si falla |
|-------|----------|
| Columnas obligatorias y `codigo_legado` | Bloqueante |
| Códigos, CUIT, matrículas y números de registro únicos en el archivo (los vacíos no cuentan) | Bloqueante (todas las filas en conflicto, no se elige una) |
| CUIT, matrícula o registro que ya existen en la Suite | Bloqueante |
| Fechas, períodos e importes legibles | Bloqueante |
| Códigos homologados | Bloqueante |
| Un cargo vigente por escribano (por su `codigo_legado`) y un titular vigente por registro | Bloqueante |
| Cargo vigente de un escribano cesante, jubilado o fallecido | Bloqueante |
| Referencias (cargo → escribano y registro, boleta → registro, pago → boleta, crédito → registro) | Bloqueante, en cascada: si una fila no se carga, tampoco las que dependen de ella |
| Importe de un crédito en cero o negativo | Bloqueante |
| DNI distinto del incluido en el CUIT (solo si vienen los dos), correo inválido, registro activo sin titular, vencimiento anterior a la emisión, pagos de boletas anuladas, pagos que no coinciden con el estado de la boleta, pagos o créditos con fecha posterior al día de la corrida | Advertencia: la fila se carga y queda para revisar |

Las observaciones identifican la fila (línea del archivo) y su `codigo_legado`; no repiten datos personales.

## Cuadratura

Para cada archivo, la corrida cuadra cuando:

1. **control = leído:** el lote trae todas las filas e importes que declara el sistema anterior;
2. **leído = cargado + rechazado:** toda fila no cargada tiene su observación bloqueante;
3. el saldo de cada registro (boletas no anuladas menos pagos menos créditos) es el mismo en origen y destino. Un saldo negativo es un **saldo a favor** del escribano; el informe muestra cuántos registros quedan a favor y cuánto suman.

Si el lote no trae `creditos.csv`, los créditos no figuran en el informe.

Lo cargado se consulta a la base, no se toma de memoria. Ninguna diferencia se compensa: si algo no cuadra, el informe muestra cuánto y por qué.

## Dónde va cada cosa

- **Padrón** (registros, personas, escribanos y cargos): a las tablas operativas de la Suite. Lo que vino vacío queda «a completar» en la ficha; sin CUIT no se le puede crear la cuenta de autogestión hasta completarlo.
- **Boletas y pagos:** a `historico_boletas` e `historico_pagos`, de solo lectura. No se convierten en boletas de la Suite, porque no tienen vigencia paramétrica ni conciliación y serían asientos ficticios. Cuentan como deuda (p. ej. para garantes de préstamos) y se consultan en el reporte «Boletas del sistema anterior».
- **Créditos:** a `historico_creditos`, de solo lectura, y se consultan en el reporte «Créditos del sistema anterior». No se imputan a ninguna boleta: restan del saldo del registro.
- **Deuda para préstamos (garantes), fail-closed:** se calcula boleta por boleta. Cada boleta no anulada y vencida a la fecha de la evaluación debe su importe menos sus propios pagos con fecha hasta ese día (nunca menos de cero); un registro debe si esa suma es positiva. Lo pagado de más en una boleta no compensa otra, un pago con fecha posterior no cuenta y **los créditos a favor no reducen esta deuda**: siguen en el saldo de la cuadratura y en los reportes, pero no habilitan a nadie.

**TODO(negocio):** decidir si el saldo a favor del sistema anterior compensa deuda (préstamos, garantes, boletas nuevas).

**TODO(negocio):** si la Caja necesita el detalle de actos de las DDJJ históricas, se agrega un archivo al formato (en una versión posterior).
