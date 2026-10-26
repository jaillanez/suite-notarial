"""Formato de intercambio v1: lo que la extracción del sistema anterior tiene que entregar.

TODO(negocio): el formato se fija acá porque el sistema anterior todavía no fue auditado
(decisión D-03). Tras la auditoría de su estructura, la extracción se escribe para producir
exactamente estos archivos; si algún dato no existe en el origen, se acuerda con la Caja.

Un lote es un directorio con un CSV por entidad (UTF-8 o Windows-1252, separador `;`, `,` o
tabulador, con encabezado) más `control.csv` con los totales que informa el sistema anterior
(filas e importes): son el «origen» contra el que se cuadra.
"""

import csv
import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

from app.modules.migracion.catalog import Entidad

VERSION_FORMATO = "1"

# (obligatorias, opcionales) por entidad.
COLUMNAS: dict[Entidad, tuple[tuple[str, ...], tuple[str, ...]]] = {
    Entidad.REGISTROS: (
        (
            "codigo_legado",
            "numero_registro",
            "circunscripcion",
            "departamento",
            "domicilio_legal",
            "estado",
        ),
        ("nombre_fantasia", "fecha_creacion"),
    ),
    Entidad.ESCRIBANOS: (
        (
            "codigo_legado",
            "cuit",
            "numero_documento",
            "apellido",
            "nombre",
            "matricula",
            "fecha_matriculacion",
            "estado",
        ),
        ("tipo_documento", "fecha_nacimiento", "email"),
    ),
    Entidad.CARGOS: (
        ("codigo_legado", "matricula", "numero_registro", "cargo", "fecha_desde"),
        ("fecha_hasta",),
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
        ("numero_boleta",),
    ),
    Entidad.PAGOS: (
        ("codigo_legado", "boleta", "fecha_pago", "importe"),
        ("medio",),
    ),
}
COLUMNAS_CONTROL = ("entidad", "filas", "importe")
MAX_FILAS = 500_000


class FormatoInvalidoError(ValueError):
    """El lote no respeta el formato: no se puede ni empezar a validar."""


@dataclass(frozen=True)
class Fila:
    numero: int  # número de línea en el archivo (el encabezado es la 1)
    datos: dict[str, str]

    @property
    def codigo(self) -> str:
        return self.datos.get("codigo_legado", "")


@dataclass
class Lote:
    filas: dict[Entidad, list[Fila]]
    # Totales que declara el sistema anterior: entidad → (filas, importe en texto o None).
    control: dict[str, tuple[int, str | None]]
    # Huella del lote (archivos y contenido): identifica la extracción en cada corrida.
    huella: str
    codificaciones: dict[str, str] = field(default_factory=dict)


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
    for entidad in Entidad:
        archivo = directorio / f"{entidad.value}.csv"
        if not archivo.is_file():
            raise FormatoInvalidoError(f"Falta {archivo.name} en el lote.")
        contenido = archivo.read_bytes()
        huella.update(archivo.name.encode() + b"\0" + hashlib.sha256(contenido).digest())
        datos, columnas, codificacion = leer_csv(contenido, archivo.name)
        obligatorias, opcionales = COLUMNAS[entidad]
        faltan = [c for c in obligatorias if c not in columnas]
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
    faltan_control = [e.value for e in Entidad if e.value not in control]
    if faltan_control:
        raise FormatoInvalidoError(
            f"control.csv: faltan los totales de {', '.join(faltan_control)}."
        )
    codificaciones["control.csv"] = codificacion
    return Lote(filas, control, huella.hexdigest(), codificaciones)
