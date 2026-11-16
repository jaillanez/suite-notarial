"""Extracción de los actos declarados en el sitio web anterior (volcado MySQL) a `actos.csv`.

El sitio web de la Caja (proveedor anterior) guarda las DDJJ de aportes en `ddjj_aportes` y cada
acto en `ddjj_aportes_detalles`: protocolo, escritura, folio, fecha, naturaleza, base, aporte
variable o fijo, exento y el aporte repartido entre titular, adscripto y a cargo. Este módulo lee
el volcado (sin ejecutar su SQL: solo interpreta los INSERT) y agrega `actos.csv` a un lote ya
extraído de las planillas de la Caja, con su fila en `control.csv`.

- Solo DDJJ presentadas (`boleta_generada = 1`); los borradores no se declararon.
- Los actos borrados en el origen (`estado <> 0`) no se migran, ni los renglones vacíos (sin
  escritura, sin naturaleza y sin aporte: una DDJJ sin movimiento).
- El registro va por su número (`registro_notarial.numero`).
- El escribano va por su CUIT contra `escribanos.csv` del lote. Si el CUIT no está (falta o
  difiere en las planillas de la Caja, a veces solo en el prefijo), por el documento que contiene
  el CUIT y, si tampoco, por apellido y nombre del sitio; en los dos casos, solo si coinciden con
  un único escribano. Si no, el acto lleva `escribano_origen` («a completar»).

No se toma nada más del sitio: ni contraseñas, ni usuarios, ni parámetros.
"""

import argparse
import csv
import re
import shutil
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.modules.migracion.catalog import Entidad
from app.modules.migracion.formato import COLUMNAS, leer_csv

TABLAS = ("registro_notarial", "ddjj_aportes", "ddjj_aportes_detalles", "sitio_web_personas")
PROTOCOLO = {"1": "GENERAL", "2": "AUXILIAR"}
CERO = Decimal("0.00")
_INSERT = re.compile(r"INSERT INTO `(\w+)` \(([^)]*)\) VALUES", re.IGNORECASE)
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a", "b": "\b"}


class VolcadoInvalidoError(ValueError):
    pass


@dataclass
class ResumenWeb:
    actos: int = 0
    importe: Decimal = CERO
    declaraciones: int = 0
    borrados: int = 0
    de_borradores: int = 0
    vacios: int = 0
    escribano_por_cuit: int = 0
    escribano_por_documento: int = 0
    escribano_por_nombre: int = 0
    escribano_a_completar: int = 0
    # CUIT del sitio → escribano del lote, cuando no fue por CUIT (para revisar con la Caja).
    asignados_por_documento: dict[str, str] = field(default_factory=dict)
    asignados_por_nombre: dict[str, str] = field(default_factory=dict)
    sin_identificar: Counter[str] = field(default_factory=Counter)


def _valores(texto: str, inicio: int) -> Iterator[tuple[list[str | None], int]]:
    """Tuplas de un `VALUES (...), (...);` desde `inicio`; devuelve cada fila y dónde sigue."""
    i, n = inicio, len(texto)
    while i < n:
        while i < n and texto[i] in " \t\r\n,":
            i += 1
        if i >= n or texto[i] == ";":
            return
        if texto[i] != "(":
            raise VolcadoInvalidoError(f"Se esperaba «(» en la posición {i}.")
        i += 1
        fila: list[str | None] = []
        actual: list[str] = []
        es_texto = False
        while True:
            if i >= n:
                raise VolcadoInvalidoError("El volcado termina dentro de una fila.")
            ch = texto[i]
            if ch == "'":
                es_texto = True
                actual = []
                i += 1
                while True:
                    if i >= n:
                        raise VolcadoInvalidoError("El volcado termina dentro de un texto.")
                    ch = texto[i]
                    if ch == "\\" and i + 1 < n:
                        actual.append(_ESCAPES.get(texto[i + 1], texto[i + 1]))
                        i += 2
                    elif ch == "'" and texto[i + 1 : i + 2] == "'":
                        actual.append("'")
                        i += 2
                    elif ch == "'":
                        i += 1
                        break
                    else:
                        actual.append(ch)
                        i += 1
                continue
            if es_texto and ch in " \t\r\n":
                i += 1
                continue
            if ch in ",)":
                crudo = "".join(actual)
                if es_texto:
                    fila.append(crudo)
                else:
                    valor = crudo.strip()
                    fila.append(None if valor.upper() == "NULL" else valor)
                actual, es_texto = [], False
                i += 1
                if ch == ")":
                    yield fila, i
                    break
                continue
            actual.append(ch)
            i += 1


def leer_volcado(texto: str, tablas: tuple[str, ...] = TABLAS) -> dict[str, list[dict[str, str]]]:
    """Filas de las tablas pedidas (columna → valor; NULL como texto vacío)."""
    salida: dict[str, list[dict[str, str]]] = {t: [] for t in tablas}
    for m in _INSERT.finditer(texto):
        tabla = m.group(1)
        if tabla not in salida:
            continue
        columnas = [c.strip().strip("`") for c in m.group(2).split(",")]
        for fila, _ in _valores(texto, m.end()):
            if len(fila) != len(columnas):
                raise VolcadoInvalidoError(f"{tabla}: una fila no tiene {len(columnas)} valores.")
            salida[tabla].append({c: (v or "") for c, v in zip(columnas, fila, strict=True)})
    return salida


def _clave(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z ]", " ", sin_tildes.lower()).split())


def _monto(valor: str) -> Decimal:
    try:
        return Decimal(valor or "0")
    except InvalidOperation as exc:
        raise VolcadoInvalidoError(f"Importe ilegible en el volcado: «{valor}».") from exc


def _texto_monto(valor: Decimal) -> str:
    return f"{valor:.2f}"


@dataclass
class _Escribanos:
    por_cuit: dict[str, str] = field(default_factory=dict)
    por_documento: dict[str, list[str]] = field(default_factory=dict)
    por_nombre: dict[str, list[str]] = field(default_factory=dict)


def _documento(cuit: str) -> str:
    """El documento dentro de un CUIT de persona (los 8 dígitos centrales)."""
    return cuit[2:10].lstrip("0") if len(cuit) == 11 else ""


def _escribanos_del_lote(directorio: Path) -> _Escribanos:
    filas, _, _ = leer_csv((directorio / "escribanos.csv").read_bytes(), "escribanos.csv")
    e = _Escribanos()
    for f in filas:
        codigo = f["codigo_legado"]
        cuit = re.sub(r"\D", "", f.get("cuit", ""))
        if cuit:
            e.por_cuit[cuit] = codigo
        documento = re.sub(r"\D", "", f.get("numero_documento", "")).lstrip("0") or _documento(cuit)
        if documento:
            e.por_documento.setdefault(documento, []).append(codigo)
        e.por_nombre.setdefault(_clave(f"{f['apellido']} {f['nombre']}"), []).append(codigo)
    return e


def extraer_actos(
    volcado: dict[str, list[dict[str, str]]], lote_base: Path
) -> tuple[list[dict[str, str]], ResumenWeb]:
    resumen = ResumenWeb()
    lote = _escribanos_del_lote(lote_base)
    nombre_web = {
        re.sub(r"\D", "", p["cuit"]): _clave(f"{p['apellido']} {p['nombre']}")
        for p in volcado["sitio_web_personas"]
        if p.get("cuit")
    }
    texto_web = {
        re.sub(r"\D", "", p["cuit"]): f"{p['apellido'].strip()}, {p['nombre'].strip()}"
        for p in volcado["sitio_web_personas"]
        if p.get("cuit")
    }
    numero_de = {r["id"]: r["numero"].strip() for r in volcado["registro_notarial"]}
    presentadas = {d["id"]: d for d in volcado["ddjj_aportes"] if d["boleta_generada"] == "1"}
    borradores = {d["id"] for d in volcado["ddjj_aportes"]} - set(presentadas)

    filas: list[dict[str, str]] = []
    declaraciones: set[str] = set()
    for a in sorted(volcado["ddjj_aportes_detalles"], key=lambda d: int(d["id"])):
        if a["id_ddjj_aporte"] in borradores:
            resumen.de_borradores += 1
            continue
        if a["estado"] != "0":
            resumen.borrados += 1
            continue
        if (
            not a["escritura_nro"].strip()
            and not a["naturaleza_acto"].strip()
            and not any(
                _monto(a[c]) for c in ("aporte_titular", "aporte_adscripto", "aporte_a_cargo")
            )
        ):
            resumen.vacios += 1
            continue
        ddjj = presentadas.get(a["id_ddjj_aporte"])
        if ddjj is None:
            raise VolcadoInvalidoError(f"Acto {a['id']}: su DDJJ no está en el volcado.")
        declaraciones.add(ddjj["id"])

        cuit = re.sub(r"\D", "", a["idnotario"])
        escribano, origen = lote.por_cuit.get(cuit, ""), ""
        por_documento = lote.por_documento.get(_documento(cuit), [])
        if escribano:
            resumen.escribano_por_cuit += 1
        elif len(por_documento) == 1:
            escribano = por_documento[0]
            resumen.escribano_por_documento += 1
            resumen.asignados_por_documento[cuit] = escribano
        else:
            candidatos = lote.por_nombre.get(nombre_web.get(cuit, ""), [])
            if len(candidatos) == 1:
                escribano = candidatos[0]
                resumen.escribano_por_nombre += 1
                resumen.asignados_por_nombre[cuit] = escribano
            else:
                origen = f"{texto_web.get(cuit, 'Sin nombre en el sitio')} (CUIT {cuit})"
                resumen.escribano_a_completar += 1
                resumen.sin_identificar[origen] += 1

        titular = _monto(a["aporte_titular"])
        adscripto = _monto(a["aporte_adscripto"])
        a_cargo = _monto(a["aporte_a_cargo"])
        importe = titular + adscripto + a_cargo
        base, variable, fijo = (
            _monto(a["base_imponible"]),
            _monto(a["aporte_porcentaje"]),
            _monto(a["aporte_fijo"]),
        )
        fecha = a["fecha"] if a["fecha"] and not a["fecha"].startswith("0000") else ""
        filas.append(
            {
                "codigo_legado": f"ACT-WEB-{a['id']}",
                "numero_registro": numero_de.get(ddjj["idregistronotarial"], ""),
                "periodo": f"{ddjj['anio']}-{int(ddjj['mes']):02d}",
                "numero_escritura": a["escritura_nro"],
                "naturaleza": " ".join(a["naturaleza_acto"].split()),
                "importe": _texto_monto(importe),
                "declaracion": f"DJ-WEB-{ddjj['id']}",
                "tipo_protocolo": PROTOCOLO.get(a["tipo_protocolo"], ""),
                "folio": a["escritura_folio"],
                "fecha_acto": fecha,
                "base_imponible": _texto_monto(base) if base else "",
                "aporte_variable": _texto_monto(variable) if variable else "",
                "aporte_fijo": _texto_monto(fijo) if fijo else "",
                "exento": "SI" if a["aporte_excento"] == "1" else "NO",
                "escribano": escribano,
                "escribano_origen": origen,
                "cargo": a["notario_autorizado"],
                "aporte_titular": _texto_monto(titular),
                "aporte_adscripto": _texto_monto(adscripto),
                "aporte_a_cargo": _texto_monto(a_cargo),
            }
        )
        resumen.importe += importe
    resumen.actos = len(filas)
    resumen.declaraciones = len(declaraciones)
    return filas, resumen


def armar_lote(volcado_sql: Path, lote_base: Path, salida: Path) -> ResumenWeb:
    """Copia el lote base a `salida` y le agrega `actos.csv` con su fila de control."""
    if salida.exists() and any(salida.iterdir()):
        raise VolcadoInvalidoError(f"{salida} ya tiene archivos: se arma en un directorio vacío.")
    if (lote_base / "actos.csv").exists():
        raise VolcadoInvalidoError("El lote base ya trae actos.csv.")
    volcado = leer_volcado(volcado_sql.read_text(encoding="utf-8"))
    filas, resumen = extraer_actos(volcado, lote_base)

    salida.mkdir(parents=True, exist_ok=True)
    for archivo in lote_base.iterdir():
        if archivo.is_file():
            shutil.copy2(archivo, salida / archivo.name)
    obligatorias, opcionales = COLUMNAS[Entidad.ACTOS]
    with (salida / "actos.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[*obligatorias, *opcionales], delimiter=";")
        writer.writeheader()
        writer.writerows(filas)

    control, columnas, _ = leer_csv((salida / "control.csv").read_bytes(), "control.csv")
    control.append(
        {c: "" for c in columnas}
        | {
            "entidad": Entidad.ACTOS.value,
            "filas": str(len(filas)),
            "importe": f"{resumen.importe:.2f}",
        }
    )
    with (salida / "control.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columnas, delimiter=";")
        writer.writeheader()
        writer.writerows(control)
    return resumen


def main(argumentos: list[str] | None = None) -> int:
    lector = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lector.add_argument("--volcado", type=Path, required=True, help="Volcado .sql del sitio")
    lector.add_argument("--lote-base", type=Path, required=True, help="Lote de las planillas")
    lector.add_argument("--salida", type=Path, required=True)
    args = lector.parse_args(argumentos)
    r = armar_lote(args.volcado, args.lote_base, args.salida)
    sys.stdout.write(
        f"actos: {r.actos} en {r.declaraciones} DDJJ presentadas, aporte {r.importe:.2f}\n"
        f"  no migrados: {r.borrados} borrados en el origen, {r.de_borradores} de borradores, "
        f"{r.vacios} renglones vacíos\n"
        f"  escribano por CUIT: {r.escribano_por_cuit}, por documento: "
        f"{r.escribano_por_documento}, por nombre: {r.escribano_por_nombre}, "
        f"a completar: {r.escribano_a_completar}\n"
    )
    for cuit, codigo in sorted(r.asignados_por_documento.items()):
        sys.stdout.write(f"  por documento: CUIT {cuit} del sitio → {codigo}\n")
    for cuit, codigo in sorted(r.asignados_por_nombre.items()):
        sys.stdout.write(f"  por nombre: CUIT {cuit} del sitio → {codigo}\n")
    for origen, cantidad in r.sin_identificar.most_common():
        sys.stdout.write(f"  a completar: {origen}: {cantidad}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
