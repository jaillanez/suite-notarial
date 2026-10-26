# Formato de intercambio para la migración (versión 1)

Lo que la extracción del sistema anterior tiene que entregar para que la Suite lo valide, lo cargue y lo cuadre. El sistema anterior todavía no fue auditado (decisión D-03 del módulo 11), así que el formato lo fija la Suite y la extracción se escribe para producirlo.

**TODO(negocio):** tras la auditoría del origen, confirmar con la Caja qué datos y qué períodos se trasladan y qué columnas no existen en el sistema anterior.

## El lote

Un directorio con seis archivos CSV:

| Archivo | Contenido |
|---------|-----------|
| `registros.csv` | Registros notariales |
| `escribanos.csv` | Personas y matrículas |
| `cargos.csv` | Titulares, adscriptos y a cargo de cada registro (vigentes e históricos) |
| `boletas.csv` | Boletas emitidas por el sistema anterior |
| `pagos.csv` | Pagos aplicados a esas boletas |
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
| Entero | Solo dígitos | Matrícula, número de registro |
| CUIT | 11 dígitos con o sin guiones | Se valida el dígito verificador (Módulo 11) |

## Columnas

Obligatorias en **negrita**.

### registros.csv
**codigo_legado**, **numero_registro**, **circunscripcion** (nombre; se crea si no existe), **departamento** (uno de los 19 de San Juan, sin importar tildes ni mayúsculas), **domicilio_legal**, **estado** (código del origen, se homologa), nombre_fantasia, fecha_creacion.

### escribanos.csv
**codigo_legado**, **cuit**, **numero_documento**, **apellido**, **nombre**, **matricula**, **fecha_matriculacion**, **estado** (se homologa), tipo_documento (DNI, LC, LE o PASAPORTE; por defecto DNI), fecha_nacimiento, email.

### cargos.csv
**codigo_legado**, **matricula**, **numero_registro**, **cargo** (se homologa: titular, adscripto o a cargo), **fecha_desde**, fecha_hasta (vacía = vigente).

### boletas.csv
**codigo_legado**, **numero_registro**, **periodo**, **fecha_emision**, **fecha_vencimiento**, **importe**, **estado** (se homologa: impaga, pagada o anulada), numero_boleta.

### pagos.csv
**codigo_legado**, **boleta** (el `codigo_legado` de la boleta), **fecha_pago**, **importe**, medio.

### control.csv
Columnas `entidad;filas;importe`, una fila por archivo (`registros`, `escribanos`, `cargos`, `boletas`, `pagos`). `importe` es obligatorio para boletas y pagos: la suma que informa el sistema anterior.

```
entidad;filas;importe
registros;150;
escribanos;222;
cargos;222;
boletas;36000;5245873210,55
pagos;34621;4180032117,10
```

## Homologación

Un JSON con cuatro tablas que traducen los códigos del origen a los valores de la Suite: `estado_escribano`, `estado_registro`, `cargo` y `estado_boleta`. La de ejemplo está en `backend/app/modules/migracion/homologacion_ejemplo.json`.

- Un código que no está en la tabla no se adivina: la fila queda observada y no se carga.
- La tabla de ejemplo se reconoce por su contenido aunque se le quite la marca `es_ejemplo`: con ella no se puede hacer la carga definitiva.
- Cada corrida guarda la huella y el contenido de su tabla. La conformidad de Tesorería y Caja cubre **el lote y la tabla**: la carga definitiva exige los dos iguales a los del simulacro firmado.

## Qué se valida

| Regla | Si falla |
|-------|----------|
| Columnas obligatorias y `codigo_legado` | Bloqueante |
| Códigos, CUIT, matrículas y números de registro únicos en el archivo | Bloqueante (todas las filas en conflicto, no se elige una) |
| CUIT, matrícula o registro que ya existen en la Suite | Bloqueante |
| Fechas, períodos e importes legibles | Bloqueante |
| Códigos homologados | Bloqueante |
| Un cargo vigente por escribano y un titular vigente por registro | Bloqueante |
| Cargo vigente de un escribano cesante, jubilado o fallecido | Bloqueante |
| Referencias (cargo → escribano y registro, boleta → registro, pago → boleta) | Bloqueante, en cascada: si una fila no se carga, tampoco las que dependen de ella |
| DNI distinto del incluido en el CUIT, correo inválido, registro activo sin titular, vencimiento anterior a la emisión, pagos de boletas anuladas, pagos que no coinciden con el estado de la boleta | Advertencia: la fila se carga y queda para revisar |

Las observaciones identifican la fila (línea del archivo) y su `codigo_legado`; no repiten datos personales.

## Cuadratura

Para cada archivo, la corrida cuadra cuando:

1. **control = leído:** el lote trae todas las filas e importes que declara el sistema anterior;
2. **leído = cargado + rechazado:** toda fila no cargada tiene su observación bloqueante;
3. el saldo de cada registro (boletas no anuladas menos pagos) es el mismo en origen y destino.

Lo cargado se consulta a la base, no se toma de memoria. Ninguna diferencia se compensa: si algo no cuadra, el informe muestra cuánto y por qué.

## Dónde va cada cosa

- **Padrón** (registros, personas, escribanos y cargos): a las tablas operativas de la Suite.
- **Boletas y pagos:** a `historico_boletas` e `historico_pagos`, de solo lectura. No se convierten en boletas de la Suite, porque no tienen vigencia paramétrica ni conciliación y serían asientos ficticios. Cuentan como deuda (p. ej. para garantes de préstamos) y se consultan en el reporte «Boletas del sistema anterior».

**TODO(negocio):** si la Caja necesita el detalle de actos de las DDJJ históricas, se agrega un archivo al formato (versión 2).
