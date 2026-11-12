"""Formato de intercambio v2: lo que la extracción del sistema anterior tiene que entregar.

TODO(negocio): el formato se fija acá porque el sistema anterior todavía no fue auditado
(decisión D-03). Tras la auditoría de su estructura, la extracción se escribe para producir
exactamente estos archivos; si algún dato no existe en el origen, se acuerda con la Caja.

Un lote es un directorio con un CSV por entidad (UTF-8 o Windows-1252, separador `;`, `,` o
tabulador, con encabezado) más `control.csv` con los totales que informa el sistema anterior
(filas e importes): son el «origen» contra el que se cuadra.

`creditos.csv` es opcional (agregado a la versión 2): los créditos a favor del escribano que el
sistema anterior registra como importes negativos. Si viene, `control.csv` declara sus totales.

`licencias.csv` es opcional (agregado a la versión 2): licencias de escribanos (el escribano por
su `codigo_legado`; `fecha_hasta` vacía = vigente). Si viene, `control.csv` declara sus filas.

Otros agregados compatibles a la versión 2: en `registros.csv`, `circunscripcion` es opcional
(vacía = «San Juan», la única circunscripción de la Caja) y `escribanos.csv` admite los datos de
la primera escritura (`primera_escritura_fecha`, `_numero`, `_registro`, `_folio`).

`control.csv` admite la columna opcional `ajuste_redondeo`: por entidad, la suma exacta de
(importe redondeado - importe del origen) de las filas que la extracción redondeó al centavo (el
detalle va en `redondeos.csv`). Con ella, la cuadratura exige control = leído - ajuste
redondeado al centavo: la diferencia de centavos queda explicada fila por fila, no compensada.

`boletas.csv` admite `escribano_origen` (nombre de quien pagó, tal como figura en el origen):
con él, `numero_registro` puede faltar y la boleta se carga «registro a completar».
"""

import csv
import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

from app.modules.migracion.catalog import OPCIONALES, Entidad

VERSION_FORMATO = "2"

# (obligatorias, opcionales) por entidad.
COLUMNAS: dict[Entidad, tuple[tuple[str, ...], tuple[str, ...]]] = {
    Entidad.REGISTROS: (
        ("codigo_legado", "numero_registro", "departamento", "domicilio_legal", "estado"),
        # `circunscripcion` vacía o ausente: CIRCUNSCRIPCION_POR_DEFECTO.
        ("circunscripcion", "nombre_fantasia", "fecha_creacion"),
    ),
    Entidad.ESCRIBANOS: (
        ("codigo_legado", "apellido", "nombre", "estado"),
        # v2: CUIT, documento, matrícula y fecha de matriculación pueden faltar en el origen
        # (históricos, altas sin matrícula): se cargan vacíos y quedan «a completar».
        (
            "cuit",
            "tipo_documento",
            "numero_documento",
            "matricula",
            "fecha_matriculacion",
            "fecha_nacimiento",
            "email",
            # Primera escritura autorizada (antigüedad). Va completa (fecha, número y registro)
            # o vacía; el folio es opcional.
            "primera_escritura_fecha",
            "primera_escritura_numero",
            "primera_escritura_registro",
            "primera_escritura_folio",
        ),
    ),
    Entidad.CARGOS: (
        # v2: el escribano se referencia por su `codigo_legado` (no todos tienen matrícula).
        ("codigo_legado", "escribano", "numero_registro", "cargo", "fecha_desde"),
        ("fecha_hasta",),
    ),
    # El escribano por su `codigo_legado`; `fecha_hasta` vacía = licencia vigente.
    Entidad.LICENCIAS: (
        ("codigo_legado", "escribano", "fecha_desde"),
        ("fecha_hasta", "motivo"),
    ),
    Entidad.BOLETAS: (
        (
            "codigo_legado",
            "numero_registro",
            "periodo",
            "fecha_emision",
            "fecha_vencimiento",
            "importe",
            "estado",
        ),
        ("numero_boleta", "escribano_origen"),
    ),
    Entidad.PAGOS: (
        ("codigo_legado", "boleta", "fecha_pago", "importe"),
        ("medio",),
    ),
    # Importe en positivo: lo que el sistema anterior le debe al escribano.
    Entidad.CREDITOS: (
        ("codigo_legado", "numero_registro", "fecha", "importe"),
        ("periodo", "concepto"),
    ),
}
COLUMNAS_CONTROL = ("entidad", "filas", "importe")
# La Caja tiene una sola circunscripción: es la que se usa si el registro no trae ninguna.
CIRCUNSCRIPCION_POR_DEFECTO = "San Juan"
MAX_FILAS = 500_000


class FormatoInvalidoError(ValueError):
    """El lote no respeta el formato: no se puede ni empezar a validar."""


@dataclass(frozen=True)
class Fila:
    numero: int  # número de línea en el archivo (el encabezado es la 1)
    datos: dict[str, str]

    @property
    def codigo(self) -> str:
        """Forma canónica (espacios unidos): la misma para el mapeo, los duplicados y las
        referencias de otros archivos (p. ej. `escribano` en cargos.csv)."""
        return " ".join(self.datos.get("codigo_legado", "").split())


@dataclass
class Lote:
    # Un archivo opcional ausente queda con la lista vacía (ver `presentes`).
    filas: dict[Entidad, list[Fila]]
    # Totales que declara el sistema anterior: entidad → (filas, importe en texto o None).
    control: dict[str, tuple[int, str | None]]
    # Huella del lote (archivos y contenido): identifica la extracción en cada corrida.
    huella: str
    codificaciones: dict[str, str] = field(default_factory=dict)
    # Ajuste de redondeo declarado en control.csv: entidad → texto (ver docstring).
    ajustes: dict[str, str] = field(default_factory=dict)
    # Archivos que trae el lote (los obligatorios siempre; los opcionales, si vinieron).
    presentes: frozenset[Entidad] = frozenset(e for e in Entidad if e not in OPCIONALES)


def _decodificar(contenido: bytes) -> tuple[str, str]:
    try:
        return contenido.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return contenido.decode("cp1252"), "cp1252"


def _separador(encabezado: str) -> str:
    return max(";,\t", key=encabezado.count)


def leer_csv(contenido: bytes, nombre: str) -> tuple[list[dict[str, str]], list[str], str]:
    """(filas, columnas, codificación). Columnas en minúsculas y sin espacios."""
    texto, codificacion = _decodificar(contenido)
    lineas = texto.splitlines()
    if not lineas:
        raise FormatoInvalidoError(f"{nombre}: el archivo está vacío.")
    lector = csv.reader(io.StringIO(texto), delimiter=_separador(lineas[0]))
    encabezado = [c.strip().lower() for c in next(lector)]
    if len(set(encabezado)) != len(encabezado):
        raise FormatoInvalidoError(f"{nombre}: hay columnas repetidas en el encabezado.")
    filas: list[dict[str, str]] = []
    for valores in lector:
        if not any(v.strip() for v in valores):
            continue
        if len(filas) >= MAX_FILAS:
            raise FormatoInvalidoError(f"{nombre}: más de {MAX_FILAS} filas.")
        if len(valores) != len(encabezado):
            # Se conserva para observarla: la validación informa la línea.
            valores = (valores + [""] * len(encabezado))[: len(encabezado)]
        filas.append({c: v.strip() for c, v in zip(encabezado, valores, strict=True)})
    return filas, encabezado, codificacion


def leer_lote(directorio: Path) -> Lote:
    if not directorio.is_dir():
        raise FormatoInvalidoError(f"{directorio} no es un directorio.")
    huella = hashlib.sha256(f"formato-{VERSION_FORMATO}".encode())
    filas: dict[Entidad, list[Fila]] = {}
    codificaciones: dict[str, str] = {}
    presentes: set[Entidad] = set()
    for entidad in Entidad:
        archivo = directorio / f"{entidad.value}.csv"
        if not archivo.is_file():
            if entidad in OPCIONALES:
                # Sin el archivo la huella no cambia: un lote sin créditos (o sin licencias) es
                # el mismo de antes.
                filas[entidad] = []
                continue
            raise FormatoInvalidoError(f"Falta {archivo.name} en el lote.")
        presentes.add(entidad)
        contenido = archivo.read_bytes()
        huella.update(archivo.name.encode() + b"\0" + hashlib.sha256(contenido).digest())
        datos, columnas, codificacion = leer_csv(contenido, archivo.name)
        obligatorias, opcionales = COLUMNAS[entidad]
        faltan = [c for c in obligatorias if c not in columnas]
        if entidad is Entidad.CARGOS and "escribano" in faltan and "matricula" in columnas:
            raise FormatoInvalidoError(
                f"{archivo.name}: es del formato v1 (cargos por «matricula»), que ya no se "
                f"acepta. El formato v{VERSION_FORMATO} referencia al escribano por su código "
                "del origen en la columna «escribano»."
            )
        if faltan:
            raise FormatoInvalidoError(f"{archivo.name}: faltan las columnas {', '.join(faltan)}.")
        conocidas = set(obligatorias) | set(opcionales)
        filas[entidad] = [
            Fila(i, {k: v for k, v in d.items() if k in conocidas})
            for i, d in enumerate(datos, start=2)
        ]
        codificaciones[archivo.name] = codificacion
    archivo = directorio / "control.csv"
    if not archivo.is_file():
        raise FormatoInvalidoError("Falta control.csv con los totales del sistema anterior.")
    contenido = archivo.read_bytes()
    huella.update(b"control.csv\0" + hashlib.sha256(contenido).digest())
    datos, columnas, codificacion = leer_csv(contenido, "control.csv")
    if [c for c in COLUMNAS_CONTROL if c not in columnas]:
        raise FormatoInvalidoError("control.csv: columnas esperadas entidad;filas;importe.")
    control: dict[str, tuple[int, str | None]] = {}
    ajustes: dict[str, str] = {}
    for d in datos:
        entidad_control = d["entidad"].strip().lower()
        if entidad_control not in {e.value for e in Entidad}:
            raise FormatoInvalidoError(f"control.csv: entidad desconocida «{d['entidad']}».")
        try:
            cantidad = int(d["filas"])
        except ValueError as exc:
            raise FormatoInvalidoError(
                f"control.csv: filas inválidas en {entidad_control}."
            ) from exc
        control[entidad_control] = (cantidad, d.get("importe") or None)
        if (d.get("ajuste_redondeo") or "").strip():
            ajustes[entidad_control] = d["ajuste_redondeo"].strip()
    faltan_control = [e.value for e in Entidad if e in presentes and e.value not in control]
    if faltan_control:
        raise FormatoInvalidoError(
            f"control.csv: faltan los totales de {', '.join(faltan_control)}."
        )
    sin_archivo = sorted(e.value for e in OPCIONALES if e not in presentes and e.value in control)
    if sin_archivo:
        raise FormatoInvalidoError(
            f"control.csv declara totales de {', '.join(sin_archivo)}, pero el lote no trae "
            "el archivo."
        )
    codificaciones["control.csv"] = codificacion
    return Lote(filas, control, huella.hexdigest(), codificaciones, ajustes, frozenset(presentes))
