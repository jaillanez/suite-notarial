"""Lectura de la planilla histórica de aportes y puntos de la Caja (hoja «Actualizada»).

Estructura esperada (la que usa la Caja hoy):
- Fila «PERIODO»: en la columna A la palabra PERIODO y, cada dos columnas, el año del
  ejercicio (1990, 1991, …); al final, «TOTAL» (se ignora: la Suite suma por su cuenta).
- Filas «Fecha de Inicio del periodo» y «Fecha de cierre del periodo», con fechas.
- Fila «AFILIADO»: debajo de cada año, el par «APORTES» / «PUNTOS».
- Una fila por afiliado (nombre en la columna A) hasta «TOTAL DE APORTES INGRESADOS».
- Filas de resumen: «TOTAL DE APORTES INGRESADOS», «CANTIDAD DE AFILIADOS (…)»,
  «CANTIDAD DE AFILIADOS X 100» (se ignora: se deduce) y «APORTE MEDIO DEL EJERCICIO».

Las cifras se leen como `Decimal` a partir de la representación más corta del número de la
planilla (la que muestra Excel), nunca operando en punto flotante. El redondeo a las escalas
de la base (aportes a centavos, puntos y aporte medio a 6 decimales, cantidad de afiliados a
4) se informa valor por valor: nada se redondea en silencio.
"""

import numbers
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.common.money import to_money, to_points, to_rate

HOJA = "Actualizada"
CERO = Decimal(0)

type Celda = str | Decimal | date | None


class PlanillaInvalidaError(Exception):
    """La planilla no tiene la estructura esperada: mensaje para la consola."""


@dataclass(frozen=True)
class Redondeo:
    fila: int  # fila de la planilla (1 = primera)
    anio: int
    campo: str
    original: Decimal
    guardado: Decimal


@dataclass(frozen=True)
class EjercicioLeido:
    anio: int
    fecha_inicio: date
    fecha_cierre: date
    total_aportes: Decimal
    cantidad_afiliados: Decimal
    aporte_medio: Decimal


@dataclass(frozen=True)
class PuntosLeidos:
    fila: int
    nombre: str
    anio: int
    aportes: Decimal
    puntos: Decimal


@dataclass
class Planilla:
    ejercicios: list[EjercicioLeido] = field(default_factory=list)
    puntos: list[PuntosLeidos] = field(default_factory=list)
    afiliados: int = 0
    # Pares aportes/puntos vacíos o en cero (no generan fila).
    celdas_vacias: int = 0
    # Filas con cifras pero sin nombre de afiliado (no se cargan; se informan).
    filas_sin_nombre: list[int] = field(default_factory=list)
    # Nombres repetidos en la hoja (se carga la primera aparición).
    filas_repetidas: list[int] = field(default_factory=list)
    redondeos: list[Redondeo] = field(default_factory=list)
    # Puntos con más de 6 decimales (se guardan redondeados a 6).
    puntos_redondeados: int = 0
    avisos: list[str] = field(default_factory=list)
    # Suma de los aportes de los afiliados (ya redondeados) por ejercicio, para la cuadratura.
    suma_aportes: dict[int, Decimal] = field(default_factory=dict)
    suma_puntos: dict[int, Decimal] = field(default_factory=dict)


# --------------------------------------------------------------------------- celdas


def numero(valor: Any) -> Decimal:
    """Número de la planilla → Decimal exacto de su representación decimal más corta."""
    if isinstance(valor, bool):
        raise PlanillaInvalidaError(f"Valor lógico donde se esperaba un número: {valor!r}")
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, numbers.Real):
        # repr() da la representación más corta que identifica al binario (lo que ve Excel).
        return Decimal(repr(valor))
    raise PlanillaInvalidaError(f"Se esperaba un número y hay {valor!r}")


def _texto(valor: Celda) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def _clave(valor: Celda) -> str:
    """Rótulo comparable: sin tildes, mayúsculas y espacios simples."""
    sin_tildes = unicodedata.normalize("NFKD", _texto(valor))
    limpio = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return " ".join(limpio.upper().split())


def _leer_xls(ruta: Path) -> list[list[Celda]]:
    import xlrd

    libro = xlrd.open_workbook(str(ruta))
    if HOJA not in libro.sheet_names():
        raise PlanillaInvalidaError(f"La planilla no tiene la hoja «{HOJA}».")
    hoja = libro.sheet_by_name(HOJA)
    filas: list[list[Celda]] = []
    for r in range(hoja.nrows):
        fila: list[Celda] = []
        for c in range(hoja.ncols):
            tipo = hoja.cell_type(r, c)
            valor = hoja.cell_value(r, c)
            if tipo == xlrd.XL_CELL_TEXT:
                fila.append(valor if valor.strip() else None)
            elif tipo == xlrd.XL_CELL_NUMBER:
                fila.append(numero(valor))
            elif tipo == xlrd.XL_CELL_DATE:
                fila.append(xlrd.xldate_as_datetime(valor, libro.datemode).date())
            elif tipo == xlrd.XL_CELL_ERROR:
                raise PlanillaInvalidaError(f"Celda con error de Excel en la fila {r + 1}.")
            else:
                fila.append(None)
        filas.append(fila)
    return filas


def _leer_xlsx(ruta: Path) -> list[list[Celda]]:
    from openpyxl import load_workbook

    libro = load_workbook(ruta, read_only=True, data_only=True)
    try:
        if HOJA not in libro.sheetnames:
            raise PlanillaInvalidaError(f"La planilla no tiene la hoja «{HOJA}».")
        filas: list[list[Celda]] = []
        for crudas in libro[HOJA].iter_rows(values_only=True):
            fila: list[Celda] = []
            for valor in crudas:
                if valor is None:
                    fila.append(None)
                elif isinstance(valor, str):
                    fila.append(valor if valor.strip() else None)
                elif isinstance(valor, datetime):
                    fila.append(valor.date())
                elif isinstance(valor, date):
                    fila.append(valor)
                else:
                    fila.append(numero(valor))
            filas.append(fila)
        return filas
    finally:
        libro.close()


def leer_celdas(ruta: Path) -> list[list[Celda]]:
    if not ruta.is_file():
        raise PlanillaInvalidaError(f"No existe el archivo {ruta}.")
    sufijo = ruta.suffix.lower()
    if sufijo == ".xls":
        return _leer_xls(ruta)
    if sufijo == ".xlsx":
        return _leer_xlsx(ruta)
    raise PlanillaInvalidaError("La planilla tiene que ser .xls o .xlsx.")


# --------------------------------------------------------------------------- estructura


def _celda(filas: list[list[Celda]], r: int, c: int) -> Celda:
    fila = filas[r]
    return fila[c] if c < len(fila) else None


def _buscar_fila(filas: list[list[Celda]], prefijo: str, desde: int = 0) -> int:
    for r in range(desde, len(filas)):
        if _clave(_celda(filas, r, 0)).startswith(prefijo):
            return r
    raise PlanillaInvalidaError(f"No se encontró la fila «{prefijo.capitalize()}…».")


def _anio(valor: Celda, columna: int) -> int:
    if isinstance(valor, Decimal) and valor == valor.to_integral_value():
        return int(valor)
    if isinstance(valor, str) and valor.strip().isdigit():
        return int(valor.strip())
    raise PlanillaInvalidaError(f"Año de ejercicio inválido en la columna {columna + 1}: {valor!r}")


def _fecha(valor: Celda, rotulo: str, anio: int) -> date:
    if isinstance(valor, date):
        return valor
    raise PlanillaInvalidaError(f"{rotulo} del ejercicio {anio}: falta la fecha o no es una fecha.")


def _cifra(valor: Celda, rotulo: str, fila: int) -> Decimal | None:
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return valor
    raise PlanillaInvalidaError(f"{rotulo} en la fila {fila}: se esperaba un número.")


def _cuantizar(
    planilla: Planilla, valor: Decimal, escala: str, *, fila: int, anio: int, campo: str
) -> Decimal:
    guardado = {"money": to_money, "points": to_points, "rate": to_rate}[escala](valor)
    if guardado != valor:
        planilla.redondeos.append(Redondeo(fila, anio, campo, valor, guardado))
    return guardado


def interpretar(filas: list[list[Celda]]) -> Planilla:
    """Arma ejercicios y puntos a partir de las celdas de la hoja «Actualizada»."""
    planilla = Planilla()
    r_periodo = _buscar_fila(filas, "PERIODO")
    r_inicio = _buscar_fila(filas, "FECHA DE INICIO", r_periodo + 1)
    r_cierre = _buscar_fila(filas, "FECHA DE CIERRE", r_periodo + 1)
    r_afiliado = _buscar_fila(filas, "AFILIADO", r_periodo + 1)
    r_total = _buscar_fila(filas, "TOTAL DE APORTES INGRESADOS", r_afiliado + 1)
    r_cantidad = next(
        (
            r
            for r in range(r_total + 1, len(filas))
            if _clave(_celda(filas, r, 0)).startswith("CANTIDAD DE AFILIADOS")
            and "X 100" not in _clave(_celda(filas, r, 0))
        ),
        None,
    )
    if r_cantidad is None:
        raise PlanillaInvalidaError("No se encontró la fila «Cantidad de afiliados…».")
    r_medio = _buscar_fila(filas, "APORTE MEDIO DEL EJERCICIO", r_total + 1)

    # Columnas de cada ejercicio: el año sobre «APORTES», «PUNTOS» a la derecha.
    columnas: list[tuple[int, int]] = []
    ancho = len(filas[r_periodo])
    c = 1
    while c < ancho:
        valor = _celda(filas, r_periodo, c)
        if _clave(valor).startswith("TOTAL"):
            break
        if valor is None:
            c += 1
            continue
        anio = _anio(valor, c)
        if _clave(_celda(filas, r_afiliado, c)) != "APORTES" or _clave(
            _celda(filas, r_afiliado, c + 1)
        ) != ("PUNTOS"):
            raise PlanillaInvalidaError(
                f"Ejercicio {anio}: debajo del año tienen que estar «APORTES» y «PUNTOS»."
            )
        columnas.append((anio, c))
        c += 2
    if not columnas:
        raise PlanillaInvalidaError("La fila «PERIODO» no tiene años de ejercicio.")
    anios = [a for a, _ in columnas]
    if len(set(anios)) != len(anios):
        raise PlanillaInvalidaError("Hay años de ejercicio repetidos en la fila «PERIODO».")

    for anio, c in columnas:
        inicio = _fecha(_celda(filas, r_inicio, c), "Fecha de inicio", anio)
        cierre = _fecha(_celda(filas, r_cierre, c), "Fecha de cierre", anio)
        if cierre <= inicio:
            raise PlanillaInvalidaError(f"Ejercicio {anio}: el cierre no es posterior al inicio.")
        if cierre.year != anio:
            planilla.avisos.append(
                f"Ejercicio {anio}: la fecha de cierre ({cierre:%d/%m/%Y}) es de otro año."
            )
        total = _cifra(_celda(filas, r_total, c), "Total de aportes", r_total + 1)
        cantidad = _cifra(_celda(filas, r_cantidad, c), "Cantidad de afiliados", r_cantidad + 1)
        medio = _cifra(_celda(filas, r_medio, c), "Aporte medio", r_medio + 1)
        if total is None or cantidad is None or medio is None:
            raise PlanillaInvalidaError(
                f"Ejercicio {anio}: faltan el total de aportes, la cantidad de afiliados o el "
                "aporte medio."
            )
        planilla.ejercicios.append(
            EjercicioLeido(
                anio=anio,
                fecha_inicio=inicio,
                fecha_cierre=cierre,
                total_aportes=_cuantizar(
                    planilla, total, "money", fila=r_total + 1, anio=anio, campo="total_aportes"
                ),
                cantidad_afiliados=_cuantizar(
                    planilla,
                    cantidad,
                    "rate",
                    fila=r_cantidad + 1,
                    anio=anio,
                    campo="cantidad_afiliados",
                ),
                aporte_medio=_cuantizar(
                    planilla, medio, "points", fila=r_medio + 1, anio=anio, campo="aporte_medio"
                ),
            )
        )
        planilla.suma_aportes[anio] = CERO
        planilla.suma_puntos[anio] = CERO

    vistos: set[str] = set()
    for r in range(r_afiliado + 1, r_total):
        nombre = " ".join(_texto(_celda(filas, r, 0)).split())
        cifras = [
            v
            for _, c in columnas
            for v in (_celda(filas, r, c), _celda(filas, r, c + 1))
            if v is not None
        ]
        if not nombre:
            if any(isinstance(v, Decimal) and v != 0 for v in cifras):
                planilla.filas_sin_nombre.append(r + 1)
            continue
        clave = _clave(nombre)
        if clave in vistos:
            planilla.filas_repetidas.append(r + 1)
            continue
        vistos.add(clave)
        planilla.afiliados += 1
        for anio, c in columnas:
            aportes = _cifra(_celda(filas, r, c), "Aportes", r + 1) or CERO
            puntos = _cifra(_celda(filas, r, c + 1), "Puntos", r + 1) or CERO
            if to_money(aportes) == 0 and to_points(puntos) == 0:
                planilla.celdas_vacias += 1
                if aportes != 0 or puntos != 0:
                    planilla.avisos.append(
                        f"Fila {r + 1}, ejercicio {anio}: cifras menores que la escala de la "
                        "base (quedan en cero y no se cargan)."
                    )
                continue
            aportes_g = _cuantizar(
                planilla, aportes, "money", fila=r + 1, anio=anio, campo="aportes"
            )
            puntos_g = to_points(puntos)
            if puntos_g != puntos:
                planilla.puntos_redondeados += 1
            planilla.puntos.append(PuntosLeidos(r + 1, nombre, anio, aportes_g, puntos_g))
            planilla.suma_aportes[anio] += aportes_g
            planilla.suma_puntos[anio] += puntos_g
    return planilla


def leer_planilla(ruta: Path) -> Planilla:
    return interpretar(leer_celdas(ruta))
