"""Lotes sintéticos en el formato de intercambio, para simulacros y ensayos (regla SEC-06).

Ningún dato es real: nombres de una lista ficticia, CUIT generados con dígito válido sobre
números de documento altos y matrículas y registros en rangos que no usa la demostración. El
`control.csv` se calcula con todas las filas, como lo declararía el sistema anterior.

Con `defectos=True` se inyectan problemas conocidos (un CUIT inválido, una matrícula repetida,
un importe con decimales de punto flotante, un estado sin homologar, dos titulares vigentes y
un pago de una boleta inexistente) para ver la validación y la cuadratura con rechazos.
"""

import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app.common.cuit import check_digit
from app.modules.migracion.catalog import Entidad
from app.modules.migracion.formato import COLUMNAS

APELLIDOS = ("Sintético", "Prueba", "Ensayo", "Ficticio", "Ejemplar", "Modelo", "Muestra")
NOMBRES = ("Ana", "Bruno", "Carla", "Diego", "Elena", "Fabián", "Gala", "Hugo", "Inés")
DEPARTAMENTOS = ("Capital", "Rawson", "Chimbas", "Rivadavia", "Santa Lucía", "Pocito")
CIRCUNSCRIPCIONES = ("Primera Circunscripción", "Segunda Circunscripción")
MATRICULA_BASE = 70_000
REGISTRO_BASE = 700
DNI_BASE = 93_000_000


@dataclass(frozen=True)
class Resumen:
    registros: int
    escribanos: int
    cargos: int
    boletas: int
    pagos: int


def _cuit(dni: int, rng: random.Random) -> str:
    for prefijo in ("20", "27") if rng.random() < 0.5 else ("27", "20"):
        cuerpo = f"{prefijo}{dni:08d}"
        digito = check_digit(cuerpo)
        if digito is not None:
            return cuerpo + str(digito)
    return f"23{dni:08d}{check_digit(f'23{dni:08d}') or 0}"


def cuit_sintetico(dni: int) -> str:
    """CUIT válido sobre un número de documento sintético (prefijo 20, o 23 si hace falta)."""
    for prefijo in ("20", "23"):
        cuerpo = f"{prefijo}{dni:08d}"
        digito = check_digit(cuerpo)
        if digito is not None:
            return cuerpo + str(digito)
    raise ValueError("No hay CUIT válido para ese documento.")


def _escribir(directorio: Path, entidad: Entidad, filas: list[dict[str, str]]) -> None:
    obligatorias, opcionales = COLUMNAS[entidad]
    with (directorio / f"{entidad.value}.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[*obligatorias, *opcionales], delimiter=";")
        writer.writeheader()
        writer.writerows(filas)


def _fecha(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _importe(valor: Decimal) -> str:
    return f"{valor:.2f}".replace(".", ",")


def generar(
    directorio: Path,
    *,
    registros: int = 20,
    periodos: int = 12,
    semilla: int = 42,
    defectos: bool = False,
    hasta: date = date(2026, 9, 30),
) -> Resumen:
    """Escribe un lote completo en `directorio` y devuelve cuántas filas tiene cada archivo."""
    rng = random.Random(semilla)  # noqa: S311 - datos de prueba, no criptografía
    directorio.mkdir(parents=True, exist_ok=True)

    filas_reg: list[dict[str, str]] = []
    filas_esc: list[dict[str, str]] = []
    filas_car: list[dict[str, str]] = []
    filas_bol: list[dict[str, str]] = []
    filas_pag: list[dict[str, str]] = []
    matricula = MATRICULA_BASE
    for i in range(registros):
        numero = REGISTRO_BASE + i
        filas_reg.append(
            {
                "codigo_legado": f"REG-{numero}",
                "numero_registro": str(numero),
                "circunscripcion": CIRCUNSCRIPCIONES[i % len(CIRCUNSCRIPCIONES)],
                "departamento": DEPARTAMENTOS[i % len(DEPARTAMENTOS)],
                "domicilio_legal": f"Calle Ficticia {100 + i}",
                "estado": "A",
                "nombre_fantasia": "",
                "fecha_creacion": "",
            }
        )
        # Titular y, a veces, un adscripto o un a cargo.
        for cargo in ("T", *(("A",) if i % 3 == 0 else ()), *(("AC",) if i % 7 == 0 else ())):
            matricula += 1
            dni = DNI_BASE + matricula
            filas_esc.append(
                {
                    "codigo_legado": f"ESC-{matricula}",
                    "cuit": _cuit(dni, rng),
                    "numero_documento": str(dni),
                    "apellido": rng.choice(APELLIDOS),
                    "nombre": rng.choice(NOMBRES),
                    "matricula": str(matricula),
                    "fecha_matriculacion": _fecha(date(2000 + rng.randint(0, 20), 3, 1)),
                    "estado": "A",
                    "tipo_documento": "DNI",
                    "fecha_nacimiento": _fecha(date(1960 + rng.randint(0, 30), 6, 15)),
                    "email": f"escribano{matricula}@ejemplo.test",
                }
            )
            filas_car.append(
                {
                    "codigo_legado": f"CAR-{matricula}",
                    "matricula": str(matricula),
                    "numero_registro": str(numero),
                    "cargo": cargo,
                    "fecha_desde": _fecha(date(2015, 1, 1)),
                    "fecha_hasta": "",
                }
            )
        # Boletas mensuales del registro; las viejas pagadas, alguna impaga o anulada.
        for k in range(periodos):
            mes = (hasta.replace(day=1) - timedelta(days=31 * (periodos - 1 - k))).replace(day=1)
            codigo = f"BOL-{numero}-{mes:%Y%m}"
            importe = Decimal(rng.randint(80_000, 400_000)) + Decimal(rng.randint(0, 99)) / 100
            sorteo = rng.random()
            estado = "P" if sorteo < 0.8 else ("I" if sorteo < 0.95 else "N")
            emision = mes.replace(day=28) + timedelta(days=5)
            filas_bol.append(
                {
                    "codigo_legado": codigo,
                    "numero_registro": str(numero),
                    "periodo": f"{mes:%m/%Y}",
                    "fecha_emision": _fecha(emision),
                    "fecha_vencimiento": _fecha(emision + timedelta(days=20)),
                    "importe": _importe(importe),
                    "estado": estado,
                    "numero_boleta": str(1000 + len(filas_bol)),
                }
            )
            if estado == "P":
                # A veces en dos pagos.
                partes = [importe] if rng.random() < 0.8 else [importe / 2, importe - importe / 2]
                partes = [p.quantize(Decimal("0.01")) for p in partes]
                partes[-1] = importe - sum(partes[:-1], Decimal("0"))
                for n, parte in enumerate(partes):
                    filas_pag.append(
                        {
                            "codigo_legado": f"PAG-{numero}-{mes:%Y%m}-{n}",
                            "boleta": codigo,
                            "fecha_pago": _fecha(emision + timedelta(days=10 + n)),
                            "importe": _importe(parte),
                            "medio": "Transferencia",
                        }
                    )

    if defectos:
        cuit = filas_esc[0]["cuit"]
        filas_esc[0]["cuit"] = cuit[:-1] + str((int(cuit[-1]) + 1) % 10)
        filas_esc[2]["matricula"] = filas_esc[1]["matricula"]
        filas_bol[3]["importe"] = "123456.789"
        filas_reg[4]["estado"] = "ZZ"
        filas_car.append(
            {
                "codigo_legado": "CAR-EXTRA",
                "matricula": filas_esc[-1]["matricula"],
                "numero_registro": filas_reg[-1]["numero_registro"],
                "cargo": "T",
                "fecha_desde": _fecha(date(2020, 1, 1)),
                "fecha_hasta": "",
            }
        )
        filas_pag.append(
            {
                "codigo_legado": "PAG-HUERFANO",
                "boleta": "BOL-INEXISTENTE",
                "fecha_pago": _fecha(hasta),
                "importe": "1000,00",
                "medio": "Efectivo",
            }
        )

    _escribir(directorio, Entidad.REGISTROS, filas_reg)
    _escribir(directorio, Entidad.ESCRIBANOS, filas_esc)
    _escribir(directorio, Entidad.CARGOS, filas_car)
    _escribir(directorio, Entidad.BOLETAS, filas_bol)
    _escribir(directorio, Entidad.PAGOS, filas_pag)

    def total(filas: list[dict[str, str]]) -> str:
        # El sistema anterior suma lo que tiene, incluso un importe con decimales de más: la
        # diferencia con lo legible es justamente lo que la cuadratura tiene que mostrar.
        return _importe(sum((Decimal(f["importe"].replace(",", ".")) for f in filas), Decimal(0)))

    with (directorio / "control.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["entidad", "filas", "importe"])
        writer.writerow([Entidad.REGISTROS.value, len(filas_reg), ""])
        writer.writerow([Entidad.ESCRIBANOS.value, len(filas_esc), ""])
        writer.writerow([Entidad.CARGOS.value, len(filas_car), ""])
        writer.writerow([Entidad.BOLETAS.value, len(filas_bol), total(filas_bol)])
        writer.writerow([Entidad.PAGOS.value, len(filas_pag), total(filas_pag)])
    return Resumen(len(filas_reg), len(filas_esc), len(filas_car), len(filas_bol), len(filas_pag))
