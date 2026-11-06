# Aportes y puntos previsionales (reglamentación de la Ley 7231)

La Caja asigna a cada afiliado **puntos** por ejercicio; los puntos determinan los beneficios
previsionales. Este documento describe lo que la Suite hace hoy con esos datos y lo que queda
pendiente de una definición oficial de la Caja.

## Ejercicio

Va del **1 de septiembre al 31 de agosto** y se identifica por el año de cierre: el ejercicio
«1990» es del 01/09/1989 al 31/08/1990. Las fechas de inicio y cierre se toman de la planilla
(no se deducen) y el cargador avisa si el cierre cae en otro año que el del rótulo.

## Qué guarda la Suite

| Tabla | Contenido |
|---|---|
| `previsional_ejercicios` | Año (único), inicio, cierre, total de aportes ingresados `Numeric(15,2)`, cantidad de afiliados `Numeric(10,4)` (la Caja estimó años anteriores a 2018 y no siempre son enteros), aporte medio `Numeric(18,6)` y origen. |
| `previsional_puntos` | Ejercicio, escribano del padrón (puede faltar), nombre tal como figura en la planilla, aportes `Numeric(15,2)`, puntos `Numeric(18,6)`, origen, fila de la planilla y cómo se vinculó (`EXACTA`, `APROXIMADA`, `MANUAL`). Único por ejercicio y nombre. |

**Inmutabilidad (regla INM):** el trigger `previsional_guard` rechaza borrar filas, modificar un
ejercicio cargado y modificar aportes, puntos u origen de una fila. Solo puede cambiar el vínculo
con el padrón, y la Suite audita cada cambio. Si la Caja corrige un dato histórico, la recarga lo
informa como diferencia y no lo sobreescribe: TODO(negocio) definir el circuito de corrección
(ajuste con resolución y auditoría).

## Carga de la planilla histórica

```bash
cd backend
.venv/bin/python -m app.modules.previsional.cargar_puntos \
  --planilla "ruta/APORTES HISTORICOS Y PUNTOS.xls" --operador caja@ejemplo --simular
```

- Lee la hoja «Actualizada» (`.xls` con `xlrd` o `.xlsx`). El operador necesita `puntos:manage`.
- `--simular` hace todo en una transacción que se revierte: sirve para revisar el informe.
- **Redondeo informado, nunca silencioso:** los aportes se guardan a centavos y los puntos y el
  aporte medio a 6 decimales (`ROUND_HALF_UP`). La consola lista cada valor redondeado por fila y
  ejercicio, y la cuadratura de cada ejercicio (total de la hoja contra la suma de los afiliados).
- Los pares vacíos o en cero no generan filas; las filas con cifras y sin nombre se informan y no
  se cargan.
- **Idempotente:** volver a correrla no duplica nada.
- **Sin datos personales en consola ni en la auditoría:** se identifica por fila. El detalle con
  nombres sale solo en `--detalle archivo.csv`, que debe tratarse como dato personal.
- `--revincular` (sin `--planilla`) reintenta vincular los puntos pendientes, por ejemplo después
  de cargar el padrón.

### Vínculo con el padrón

La planilla identifica al afiliado solo por el nombre. Para no asignar puntos a otra persona:

1. **Exacta:** el nombre normalizado (sin tildes, mayúsculas, signos ni espacios dobles) coincide
   con «apellido nombre» de un único escribano.
2. **Aproximada, solo si es única:** todas las palabras de la planilla están en el nombre del
   escribano (una inicial vale por una palabra con esa letra). Queda vinculada pero listada para
   revisar.
3. **Sin vincular:** ningún candidato o más de uno. Queda en la lista «Puntos sin vincular»
   (Suite → Aportes y puntos), donde quien tiene `puntos:manage` la vincula o confirma a mano.
   Cambiar un vínculo ya confirmado exige motivo. Todo queda en `audit_security_logs`.

Un nombre ya vinculado en otros ejercicios conserva ese vínculo en los ejercicios nuevos.

## Consulta

- **Personal** (`puntos:read_all`: Administración, Caja, Tesorería y Auditoría, los mismos roles
  que ven el padrón): en la ficha del escribano, la sección «Aportes y puntos (Ley 7231)» con la
  tabla por ejercicio, los totales y el PDF «Informe de aportes y puntos», equivalente al
  «Informe para Escribano» de la Caja.
- **Escribano** (`puntos:read_own`): «Mis puntos» con su propio informe y el PDF. Pedir el de
  otro escribano devuelve 403 y queda auditado.
- **Resumen por ejercicio:** reporte «Aportes y puntos por ejercicio» (Reportes), con paginación
  en el servidor y exportación XLSX/CSV con los mismos filtros y totales.

## Crédito de puntos de ejercicios nuevos — PENDIENTE (TODO(negocio))

La Suite **no calcula puntos**. Existe la estructura (servicio `calcular_puntos_ejercicio` y la
acción «Calcular puntos de un ejercicio», deshabilitada) y responde *501 Not Implemented* con el
motivo «Falta la regla oficial de cálculo de la Caja». No se implementará ninguna fórmula hasta
que la Caja la apruebe por escrito.

### Hipótesis a confirmar con la Caja (NO es una regla)

En todos los ejercicios de la planilla histórica se observa que:

- `aporte medio del ejercicio = total de aportes ingresados ÷ (cantidad de afiliados × 100)`, y
- la suma de los puntos de todos los afiliados ≈ `100 × cantidad de afiliados`,

lo que sugiere `puntos del afiliado = aportes del afiliado ÷ aporte medio del ejercicio`. En
varios ejercicios anteriores a 2018 la suma no da exacta (la propia planilla aclara que la
cantidad de afiliados de esos años es estimada).

Preguntas para la Caja antes de implementar:

1. ¿La fórmula es la de arriba? ¿Está en una resolución o reglamentación (número y fecha)?
2. ¿Qué aportes cuentan: los devengados del ejercicio o los efectivamente pagados (conciliados
   por Tesorería) dentro del ejercicio? ¿Cómo se tratan los pagos fuera de término de ejercicios
   anteriores?
3. ¿Qué es «cantidad de afiliados»: activos al cierre, con al menos un aporte, promedio?
4. ¿Con cuántos decimales y con qué regla se redondean los puntos?
5. ¿Se recalculan ejercicios cerrados si entra un pago tardío, o el ajuste va al ejercicio en que
   se cobra?
6. ¿Quién aprueba la acreditación (cuatro ojos) y desde cuándo rige?

Cuando la regla esté aprobada, la acreditación seguirá las reglas de la Suite: cálculo solo en
el servidor con `Decimal`, parámetros versionados con vigencia (Fase 3), referencia a la vigencia
usada en cada fila (SNAP), ratificación humana y auditoría.
