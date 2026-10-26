# Manual de corte y reversa

Procedimiento para pasar del sistema anterior a la Suite y, si algo sale mal, volver atrás en menos de 30 minutos (módulo 11, §2 y §5). Complementa el [formato de intercambio](formato-intercambio-migracion.md).

## Roles

| Rol | Quién | Qué hace |
|-----|-------|----------|
| Comité de contingencia | Gerente de Caja, Responsable de Sistemas, Auditor General | Decide «sigue» o «reversa» y firma el acta |
| Operador | Usuario con `migracion:ejecutar` (Administración) | Corre simulacros, respaldo, carga definitiva y reversa por consola |
| Tesorería y Caja | Una persona de cada área (distintas) | Revisan cuadratura, observaciones y tabla de homologación, y dan conformidad en la Suite (Migración) |

## Antes del corte

1. **Auditoría del sistema anterior (D-03):** motor, esquema, codificación, volúmenes y adjuntos. Con eso se escribe la extracción al formato de intercambio. **TODO(negocio):** períodos que se migran y qué queda en el histórico de solo lectura.
2. **Tabla de homologación aprobada:** la arma Sistemas con la Caja. La de ejemplo nunca sirve para la definitiva.
3. **Simulacros:** al menos `MIGRACION_SIMULACROS_MINIMOS` (3) que cuadren con el mismo lote y la misma tabla. Cada uno se revisa en *Migración*: cuadratura, saldos por registro, observaciones y tabla de homologación.

   ```bash
   cd backend && .venv/bin/python -m app.modules.migracion.cli simulacro --lote /ruta/al/lote --homologacion /ruta/homologacion.json --operador operador@caja
   ```

4. **Ensayo de corte con el volumen real** (base `suite_notarial_ensayo`, que crea `make db`). Repite todo el circuito y cronometra la reversa:

   ```bash
   make ensayo-corte registros=150 periodos=240
   ```

   El informe queda en `backend/var/ensayo-corte/informe-ensayo.md`. Referencia en desarrollo, con 150 registros, 222 escribanos, 36.000 boletas y 34.600 pagos: unos 6 s por simulacro, 6 s la carga definitiva y **menos de 1 s la reversa** (respaldo, restauración y verificación). **TODO(infra):** repetirlo en el servidor de producción antes del corte.

## Ventana de corte

| Hora | Paso | Responsable |
|------|------|-------------|
| Viernes 18:00 | Sistema anterior en **solo lectura** (se conserva intacto para la reversa B) | Sistemas |
| 18:30 | Extracción final al formato de intercambio | Sistemas |
| 19:30 | Simulacro con ese lote y la tabla aprobada. Debe cuadrar | Operador |
| 20:00 | Conformidad de Tesorería y de Caja sobre ese simulacro | Tesorería, Caja |
| 20:30 | Respaldo de la base de la Suite | Operador |
| 20:45 | Carga definitiva | Operador |
| 21:00 | Verificación y «sigue» o «reversa» | Comité |
| Lunes 08:00 | Apertura a escribanos y personal | Comité |

Comandos (desde `backend/`, con el `.env` de producción):

```bash
.venv/bin/python -m app.modules.migracion.cli respaldo --salida /respaldos/antes-de-la-carga.dump
.venv/bin/python -m app.modules.migracion.cli definitiva --lote /ruta/al/lote --homologacion /ruta/homologacion.json --operador operador@caja
```

La carga definitiva se niega si falta algo: tabla de ejemplo, simulacros insuficientes, último simulacro del lote sin cuadrar o sin las dos conformidades, o una carga definitiva previa. También se revierte sola, sin cargar nada, si no cuadra por sí misma o si rechaza filas distintas de las del simulacro firmado (por ejemplo, porque alguien cargó datos en la Suite entre medio).

### Verificación después de la carga

- La corrida definitiva figura **Cargada** y **Cuadra** en *Migración*.
- `GET /api/health` responde `db: up`.
- Ingreso de un usuario de cada rol.
- Un escribano migrado con sus cargos; un registro con su titular.
- Reporte «Boletas del sistema anterior»: totales iguales al control del origen.

## Reversa A: volver la Suite al respaldo

Para una carga equivocada o incompleta detectada en la ventana. Borra y recrea el esquema en una sola transacción: o se completa o no cambia nada.

```bash
.venv/bin/python -m app.modules.migracion.cli reversa --respaldo /respaldos/antes-de-la-carga.dump --confirmo-reversa
```

Corre con el rol dueño del esquema, sin superusuario. Después se repite la verificación y se registra en el acta.

## Reversa B: volver al sistema anterior (primeras 48 horas)

Objetivo: **menos de 30 minutos** desde la decisión del comité.

| Paso | Tiempo objetivo |
|------|----------------:|
| 1. Decisión del comité y acta de reversa | 5 min |
| 2. Suite en mantenimiento (proxy con página de aviso) | 2 min |
| 3. Exportar lo operado en la Suite desde el corte (ver abajo) | 10 min |
| 4. Sistema anterior otra vez en lectura y escritura | 3 min |
| 5. DNS o proxy apuntando al sistema anterior | 5 min |
| 6. Prueba de ingreso y aviso a escribanos y personal | 5 min |

**Lo operado en la Suite durante la ventana** (DDJJ, comprobantes, conciliaciones, préstamos) se exporta desde *Reportes* (Boletas emitidas, Pagos y conciliaciones, Registro de auditoría) en CSV. Cada exportación queda auditada. Se reingresa a mano en el sistema anterior, con la firma de Tesorería.

**TODO(infra):** los pasos 2, 4 y 5 dependen de la infraestructura de producción (proxy, DNS, servidor del sistema anterior). Se documentan con sus comandos y se cronometran en un ensayo general antes del corte.

## Acta (plantilla)

```
ACTA DE CORTE / REVERSA — Suite Notarial, Caja Notarial de San Juan
Fecha y hora: ____________________
Corrida definitiva: ______________ (huella del lote ____________, homologación ____________)
Resultado de la cuadratura: Cuadra / No cuadra   Observaciones bloqueantes: ____
Conformidad de Tesorería: ______________   Conformidad de Caja: ______________
Decisión: SIGUE / REVERSA A / REVERSA B   Motivo: ______________________________
Tiempos (reversa): decisión ____ inicio ____ fin ____ total ____ min
Firmas: Gerente de Caja ____________ Responsable de Sistemas ____________ Auditor General ____________
```
