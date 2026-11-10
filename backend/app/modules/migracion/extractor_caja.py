"""Extracción desde las planillas de la Caja hacia el formato de intercambio v2.

`python -m app.modules.migracion.extractor_caja --listado XLSX --pagos XLSX --salida DIR
[--registros CSV]`

Fuentes (exportaciones del sistema en uso, entregadas por la Caja el 05/11/2026):

- «Listado historico de escribanos.xlsx», hoja TODOS: una fila por escribano y registro
  (quien fue adscripto y después titular aparece dos veces). Trae CUIT, alta, baja y estado,
  pero no la matrícula.
- «Historico de aportes pagados por dia.xlsx», hoja aportes: una fila por cuota mensual de
  cada escribano, con lo pagado y cuándo. Su columna MATRICULA trae la matrícula (número
  corto) en algunas filas y el CUIT en otras: de ahí sale la matrícula de cada persona.
- `--registros`: CSV que entrega la Caja con `numero_registro;departamento;circunscripcion`
  (las planillas no traen esos datos). Sin él, los registros quedan observados. La Caja tiene
  una sola circunscripción: sin dato, cada registro va a «San Juan».

Las licencias salen del listado (columnas ALTA DE LICENCIA y BAJA DE LICENCIA): una por
persona y fecha de inicio; sin BAJA DE LICENCIA queda vigente (`licencias.csv`).

Nadie queda afuera: quien no tiene CUIT, matrícula o fecha de alta se carga con el dato vacío
(«a completar»). Lo que la extracción tuvo que decidir queda en `extraccion.csv` (fila del
Excel, qué se hizo y por qué) y los importes redondeados en `redondeos.csv`, para que
Tesorería los revise antes de firmar el simulacro. Los archivos de salida tienen datos
personales: se generan sólo en carpetas privadas (nunca en el repositorio).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook

CENTAVO = Decimal("0.01")
SEPARADOR = ";"

COLUMNAS = {
    "registros": (
        "codigo_legado",
        "numero_registro",
        "circunscripcion",
        "departamento",
        "domicilio_legal",
        "estado",
    ),
    "escribanos": (
        "codigo_legado",
        "cuit",
        "numero_documento",
        "apellido",
        "nombre",
        "matricula",
        "fecha_matriculacion",
        "estado",
        "tipo_documento",
        "fecha_nacimiento",
        "email",
    ),
    "cargos": (
        "codigo_legado",
        "escribano",
        "numero_registro",
        "cargo",
        "fecha_desde",
        "fecha_hasta",
    ),
    "licencias": ("codigo_legado", "escribano", "fecha_desde", "fecha_hasta", "motivo"),
    "boletas": (
        "codigo_legado",
        "numero_registro",
        "periodo",
        "fecha_emision",
        "fecha_vencimiento",
        "importe",
        "estado",
        "numero_boleta",
    ),
    "pagos": ("codigo_legado", "boleta", "fecha_pago", "importe", "medio"),
    "creditos": ("codigo_legado", "numero_registro", "fecha", "importe", "periodo", "concepto"),
}
# Concepto con el que la Caja registra los créditos a favor que surgen de una inspección.
CONCEPTO_INSPECCION = "DIF DE INSPECCION"
# La Caja tiene una sola circunscripción (formato v2: CIRCUNSCRIPCION_POR_DEFECTO).
CIRCUNSCRIPCION = "San Juan"


# ------------------------------------------------------------------ valores


def texto(valor: object) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return re.sub(r"\s+", " ", str(valor)).strip()


def clave_nombre(valor: str) -> str:
    """Nombre comparable: sin tildes, mayúsculas, sin comas ni espacios repetidos."""
    sin_tildes = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z ]", "", re.sub(r"[,\s]+", " ", sin_tildes.upper())).strip()


def digitos(valor: object) -> str:
    return re.sub(r"\D", "", texto(valor))


def cuit_valido(cuit: str) -> bool:
    if len(cuit) != 11:
        return False
    suma = sum(int(a) * b for a, b in zip(cuit[:10], (5, 4, 3, 2, 7, 6, 5, 4, 3, 2), strict=True))
    verificador = 11 - suma % 11
    verificador = 0 if verificador == 11 else 9 if verificador == 10 else verificador
    return verificador == int(cuit[10])


def una_fecha(valor: object) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    t = texto(valor)
    for patron, orden in (
        (r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", (3, 2, 1)),
        (r"(\d{4})-(\d{1,2})-(\d{1,2})", (1, 2, 3)),
    ):
        coincide = re.fullmatch(patron, t)
        if coincide:
            try:
                return date(*(int(coincide.group(i)) for i in orden))
            except ValueError:
                return None
    return None


def importe(valor: object) -> Decimal | None:
    """Excel guarda los importes como número binario: se toma su representación decimal más
    corta (la que muestra la planilla), nunca la expansión binaria."""
    if valor is None or texto(valor) == "":
        return None
    try:
        return Decimal(repr(valor)) if isinstance(valor, float) else Decimal(texto(valor))
    except InvalidOperation:
        return None


def iso(valor: date | None) -> str:
    return valor.isoformat() if valor else ""


def monto(valor: Decimal) -> str:
    return f"{valor:.2f}"


# ------------------------------------------------------------------ lectura


def filas_hoja(
    ruta: Path, hoja: str, fila_encabezado: int
) -> Iterator[tuple[int, dict[str, object]]]:
    """(número de fila del Excel, {encabezado: valor}). Encabezados repetidos llevan sufijo."""
    libro = load_workbook(ruta, read_only=True, data_only=True)
    try:
        filas = libro[hoja].iter_rows(values_only=True)
        encabezado: list[str] = []
        for numero, valores in enumerate(filas, start=1):
            if numero < fila_encabezado:
                continue
            if numero == fila_encabezado:
                vistos: dict[str, int] = defaultdict(int)
                for celda in valores:
                    nombre = texto(celda).upper() or "_"
                    vistos[nombre] += 1
                    encabezado.append(
                        nombre if vistos[nombre] == 1 else f"{nombre}_{vistos[nombre]}"
                    )
                continue
            if all(v is None or texto(v) == "" for v in valores):
                continue
            yield numero, dict(zip(encabezado, valores, strict=False))
    finally:
        libro.close()


# ------------------------------------------------------------------ modelo intermedio


@dataclass
class Persona:
    codigo: str
    cuit: str
    apellido: str
    nombre: str
    nacimiento: date | None
    email: str
    dni: str = ""
    variantes: set[str] = field(default_factory=set)
    filas: list[int] = field(default_factory=list)
    altas: list[date] = field(default_factory=list)
    estado: str = ""
    estado_fecha: date | None = None
    matricula: int | None = None


@dataclass
class FilaCargo:
    fila: int
    persona: str
    registro: int
    cargo: str
    desde: date | None
    hasta: date | None
    domicilio: str


@dataclass
class FilaLicencia:
    fila: int
    persona: str
    desde: date
    hasta: date | None


@dataclass
class Lote:
    # Filas e importes leídos de las planillas antes de transformar nada (el «origen»).
    origen: dict[str, tuple[int, Decimal]] = field(default_factory=dict)
    archivos: dict[str, list[dict[str, str]]] = field(default_factory=lambda: defaultdict(list))
    extraccion: list[dict[str, str]] = field(default_factory=list)
    redondeos: list[dict[str, str]] = field(default_factory=list)

    def anotar(self, fuente: str, fila: int, codigo: str, accion: str, motivo: str) -> None:
        self.extraccion.append(
            {
                "fuente": fuente,
                "fila_excel": str(fila),
                "codigo_legado": codigo,
                "accion": accion,
                "motivo": motivo,
            }
        )

    def redondear(self, fuente: str, fila: int, codigo: str, valor: Decimal) -> Decimal:
        redondeado = valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)
        if redondeado != valor:
            self.redondeos.append(
                {
                    "fuente": fuente,
                    "fila_excel": str(fila),
                    "codigo_legado": codigo,
                    "original": str(valor),
                    "redondeado": monto(redondeado),
                }
            )
        return redondeado


LISTADO = "listado"
PAGOS = "pagos"


def _codigo_persona(cuit: str, apellido: str, nombre: str) -> str:
    if cuit:
        return f"ESC-{cuit}"
    return "ESC-N-" + clave_nombre(f"{apellido} {nombre}").replace(" ", "-")


def leer_listado(
    filas: Iterable[tuple[int, dict[str, object]]],
    lote: Lote,
    licencias: list[FilaLicencia] | None = None,
) -> tuple[dict[str, Persona], list[FilaCargo]]:
    """Personas (una por CUIT o, sin CUIT, por nombre) y las filas de cargo de cada una. Si se
    pasa `licencias`, junta ahí las licencias de cada fila (ALTA / BAJA DE LICENCIA)."""
    personas: dict[str, Persona] = {}
    cargos: list[FilaCargo] = []
    if licencias is None:
        licencias = []
    for numero, f in filas:
        apellido = texto(f.get("APELLIDO DEL NOTARIO"))
        if not apellido:
            lote.anotar(LISTADO, numero, "", "FILA_SIN_APELLIDO", "Fila sin apellido: no se lee.")
            continue
        nombre = texto(f.get("NOMBRE DEL NOTARIO"))
        # Algunas filas traen «APELLIDO, NOMBRE» completo en las dos columnas.
        if "," in apellido:
            apellido, _, nombre = (parte.strip() for parte in apellido.partition(","))
        documento = digitos(f.get("CUIL/CUIT/DNI"))
        cuit = documento if len(documento) == 11 and cuit_valido(documento) else ""
        dni = documento if 7 <= len(documento) <= 8 else (cuit[2:10].lstrip("0") if cuit else "")
        if documento and not cuit and not dni:
            lote.anotar(
                LISTADO,
                numero,
                "",
                "CUIT_REVISAR",
                "El CUIT del listado no es válido: se busca en la planilla de pagos.",
            )
        codigo = _codigo_persona(cuit, apellido, nombre)
        persona = personas.setdefault(
            codigo,
            Persona(
                codigo,
                cuit,
                apellido,
                nombre,
                una_fecha(f.get("FECHA DE NACIMIENTO")),
                texto(f.get("CORREO ELECTRÓNICO")).lower(),
                dni,
            ),
        )
        persona.variantes |= {
            v
            for v in (
                clave_nombre(f"{apellido} {nombre}"),
                clave_nombre(texto(f.get("NOMBRE DEL NOTARIO_2"))),
            )
            if v
        }
        persona.filas.append(numero)
        alta, baja = una_fecha(f.get("ALTA")), una_fecha(f.get("BAJA"))
        if alta:
            persona.altas.append(alta)
        # El estado de la persona es el de su fila más reciente (sin baja, o la de baja más nueva).
        momento = date.max if baja is None else baja
        if persona.estado_fecha is None or momento >= persona.estado_fecha:
            persona.estado, persona.estado_fecha = texto(f.get("ESTADO")).upper(), momento
        alta_licencia = una_fecha(f.get("ALTA DE LICENCIA"))
        baja_licencia = una_fecha(f.get("BAJA DE LICENCIA"))
        if alta_licencia:
            licencias.append(FilaLicencia(numero, codigo, alta_licencia, baja_licencia))
        elif baja_licencia or texto(f.get("ALTA DE LICENCIA")):
            lote.anotar(
                LISTADO,
                numero,
                codigo,
                "LICENCIA_SIN_INICIO",
                "La fila trae datos de licencia sin una fecha de alta válida: no se migra.",
            )
        registro = digitos(f.get("REGISTRO"))
        if registro:
            cargos.append(
                FilaCargo(
                    numero,
                    codigo,
                    int(registro),
                    texto(f.get("CARÁCTER")).upper(),
                    alta,
                    baja,
                    texto(f.get("DOMICILIO ESCRIBANIA")),
                )
            )
    # La misma persona puede figurar con CUIT en una fila y sin CUIT en otra. Se unen sólo con
    # el mismo apellido y nombre completos (al menos dos palabras) y sin fechas de nacimiento
    # distintas; un parecido sin esa confirmación queda anotado y sin unir.
    for codigo in [c for c, p in personas.items() if not p.cuit]:
        sin_cuit = personas[codigo]
        clave = clave_nombre(f"{sin_cuit.apellido} {sin_cuit.nombre}")
        parecidos = [p for p in personas.values() if p.cuit and p.variantes & sin_cuit.variantes]
        iguales = [
            p
            for p in parecidos
            if len(clave.split()) >= 2
            and clave_nombre(f"{p.apellido} {p.nombre}") == clave
            and (
                p.nacimiento is None
                or sin_cuit.nacimiento is None
                or p.nacimiento == sin_cuit.nacimiento
            )
        ]
        if len(iguales) != 1:
            if parecidos:
                lote.anotar(
                    LISTADO,
                    sin_cuit.filas[0],
                    codigo,
                    "IDENTIDAD_A_CONFIRMAR",
                    "Se parece a otra persona del listado que tiene CUIT: no se unen, revisar.",
                )
            continue
        destino = iguales[0]
        lote.anotar(
            LISTADO,
            sin_cuit.filas[0],
            destino.codigo,
            "UNION_POR_NOMBRE",
            "Fila sin CUIT unida a la persona con el mismo nombre que sí lo tiene.",
        )
        destino.filas += sin_cuit.filas
        destino.altas += sin_cuit.altas
        destino.variantes |= sin_cuit.variantes
        if sin_cuit.estado_fecha and (
            destino.estado_fecha is None or sin_cuit.estado_fecha > destino.estado_fecha
        ):
            destino.estado, destino.estado_fecha = sin_cuit.estado, sin_cuit.estado_fecha
        for cargo in cargos:
            if cargo.persona == codigo:
                cargo.persona = destino.codigo
        for licencia in licencias:
            if licencia.persona == codigo:
                licencia.persona = destino.codigo
        del personas[codigo]
    return personas, cargos


def matriculas_desde_pagos(
    filas: list[tuple[int, dict[str, object]]], personas: dict[str, Persona], lote: Lote
) -> dict[str, str]:
    """La matrícula de cada persona y el vínculo «NOMBRES de la planilla de pagos» → persona.

    En la planilla de pagos una misma persona tiene filas con su matrícula (número corto) y
    filas con su CUIT: se las une por el nombre tal como figura en esa planilla.
    """
    por_cuit = {p.cuit: p.codigo for p in personas.values() if p.cuit}

    def por_nombre(nombres: str) -> tuple[set[str], bool]:
        """Igual nombre, o todas sus palabras dentro de un nombre del listado
        («RODAS AUGUSTO» → «RODAS AUGUSTO JOSE»), o igual sin espacios («CONTEGRAND»)."""
        clave = clave_nombre(nombres)
        palabras, junto = set(clave.split()), clave.replace(" ", "")

        def exacto(v: str) -> bool:
            return v == clave

        for criterio in (
            exacto,
            lambda v: palabras <= set(v.split()),
            lambda v: v.replace(" ", "").startswith(junto),
        ):
            hallados = {
                p.codigo for p in personas.values() if any(v and criterio(v) for v in p.variantes)
            }
            if hallados:
                return hallados, criterio is exacto
        return set(), False

    cortas: dict[str, set[int]] = defaultdict(set)
    cuits: dict[str, set[str]] = defaultdict(set)
    for _, f in filas:
        nombres = texto(f.get("NOMBRES"))
        valor = digitos(f.get("MATRICULA"))
        if 1 <= len(valor) <= 5:
            cortas[nombres].add(int(valor))
        elif len(valor) in (10, 11):
            cuits[nombres].add(valor.zfill(11))
    vinculo: dict[str, str] = {}
    for nombres in {texto(f.get("NOMBRES")) for _, f in filas}:
        candidatos = {por_cuit[c] for c in cuits[nombres] if c in por_cuit}
        seguro = bool(candidatos)
        if not candidatos:
            candidatos, seguro = por_nombre(nombres)
        if len(candidatos) == 1:
            codigo = candidatos.pop()
            vinculo[nombres] = codigo
            persona = personas[codigo]
            if not seguro:
                lote.anotar(
                    PAGOS,
                    0,
                    codigo,
                    "VINCULO_POR_NOMBRE",
                    "Pagos unidos a esta persona por un nombre parecido (no idéntico): revisar.",
                )
            # CUIT faltante o inválido en el listado: se toma el de la planilla de pagos si es
            # uno solo, válido, de nadie más y el vínculo no depende de un nombre parecido.
            validos = {c for c in cuits[nombres] if cuit_valido(c) and c not in por_cuit}
            if seguro and not persona.cuit and len(validos) == 1:
                persona.cuit = validos.pop()
                persona.dni = persona.cuit[2:10].lstrip("0")
                por_cuit[persona.cuit] = codigo
                lote.anotar(
                    PAGOS,
                    0,
                    codigo,
                    "CUIT_DE_PAGOS",
                    "El listado no trae un CUIT válido: se toma el de la planilla de pagos.",
                )
    asignadas: dict[int, str] = {}
    for nombres, codigo in vinculo.items():
        if len(cortas[nombres]) == 1:
            matricula = next(iter(cortas[nombres]))
            if matricula in asignadas and asignadas[matricula] != codigo:
                lote.anotar(
                    PAGOS,
                    0,
                    codigo,
                    "MATRICULA_A_COMPLETAR",
                    f"La matrícula {matricula} figura para dos personas: no se usa en ninguna.",
                )
                personas[asignadas[matricula]].matricula = None
                continue
            asignadas[matricula] = codigo
            personas[codigo].matricula = matricula
    return vinculo


def escribir_padron(
    personas: dict[str, Persona],
    cargos: list[FilaCargo],
    departamentos: dict[int, dict[str, str]],
    lote: Lote,
) -> None:
    for p in personas.values():
        if p.matricula is None:
            lote.anotar(
                LISTADO,
                p.filas[0],
                p.codigo,
                "MATRICULA_A_COMPLETAR",
                "No figura la matrícula en las planillas.",
            )
        if not p.cuit:
            lote.anotar(
                LISTADO, p.filas[0], p.codigo, "CUIT_A_COMPLETAR", "El listado no trae CUIT."
            )
        alta = min(p.altas) if p.altas else None
        if alta is None:
            lote.anotar(
                LISTADO,
                p.filas[0],
                p.codigo,
                "FECHA_A_COMPLETAR",
                "El listado no trae fecha de alta.",
            )
        lote.archivos["escribanos"].append(
            {
                "codigo_legado": p.codigo,
                "cuit": p.cuit,
                "numero_documento": p.dni,
                "apellido": p.apellido,
                "nombre": p.nombre,
                "matricula": str(p.matricula) if p.matricula else "",
                "fecha_matriculacion": iso(alta),
                "estado": p.estado,
                "tipo_documento": "DNI",
                "fecha_nacimiento": iso(p.nacimiento),
                "email": p.email,
            }
        )
    vigentes_titular: set[int] = set()
    domicilios: dict[int, tuple[date, str]] = {}
    for c in cargos:
        registro = c.registro
        codigo = f"CAR-{c.fila}"
        if c.hasta is None and c.cargo == "TITULAR":
            vigentes_titular.add(registro)
        desde = c.desde or date.min
        if c.domicilio and (registro not in domicilios or desde >= domicilios[registro][0]):
            domicilios[registro] = (desde, c.domicilio)
        if not c.cargo:
            lote.anotar(
                LISTADO,
                c.fila,
                codigo,
                "CARGO_SIN_CARACTER",
                "La fila no dice si es titular o adscripto: queda observada.",
            )
        lote.archivos["cargos"].append(
            {
                "codigo_legado": codigo,
                "escribano": c.persona,
                "numero_registro": str(registro),
                "cargo": c.cargo,
                "fecha_desde": iso(c.desde),
                "fecha_hasta": iso(c.hasta),
            }
        )
    numeros = sorted({c.registro for c in cargos} | set(departamentos))
    for numero in numeros:
        dato = departamentos.get(numero, {})
        if not dato:
            lote.anotar(
                LISTADO,
                0,
                f"REG-{numero}",
                "REGISTRO_SIN_DEPARTAMENTO",
                "Falta el departamento y la circunscripción que informa la Caja.",
            )
        lote.archivos["registros"].append(
            {
                "codigo_legado": f"REG-{numero}",
                "numero_registro": str(numero),
                "circunscripcion": dato.get("circunscripcion") or CIRCUNSCRIPCION,
                "departamento": dato.get("departamento", ""),
                "domicilio_legal": domicilios.get(numero, (date.min, "A completar"))[1],
                "estado": "CON_TITULAR" if numero in vigentes_titular else "SIN_TITULAR",
            }
        )


# Estados del listado de quien ya no ejerce: una licencia sin regreso queda para revisar.
SIN_EJERCICIO = ("FALLECIDO", "JUBILADO", "CESANTE", "BAJA")


def escribir_licencias(
    personas: dict[str, Persona], licencias: list[FilaLicencia], lote: Lote
) -> None:
    """Una licencia por persona y fecha de inicio: la misma licencia puede repetirse en las
    filas de la persona (una por registro en que estuvo)."""
    vistas: dict[tuple[str, date], FilaLicencia] = {}
    for lic in licencias:
        clave = (lic.persona, lic.desde)
        anterior = vistas.get(clave)
        if anterior is None:
            vistas[clave] = lic
            continue
        if anterior.hasta != lic.hasta:
            lote.anotar(
                LISTADO,
                lic.fila,
                f"LIC-{anterior.fila}",
                "LICENCIA_REPETIDA_DISTINTA",
                "La misma licencia figura con otra fecha de baja en otra fila: se usa la "
                "primera, revisar.",
            )
    for lic in sorted(vistas.values(), key=lambda x: x.fila):
        codigo = f"LIC-{lic.fila}"
        persona = personas.get(lic.persona)
        if lic.hasta is None and persona is not None and persona.estado.startswith(SIN_EJERCICIO):
            lote.anotar(
                LISTADO,
                lic.fila,
                codigo,
                "LICENCIA_A_REVISAR",
                f"Licencia sin fecha de baja de una persona en estado «{persona.estado}»: la "
                "validación la rechaza hasta que se cargue la baja de la licencia.",
            )
        lote.archivos["licencias"].append(
            {
                "codigo_legado": codigo,
                "escribano": lic.persona,
                "fecha_desde": iso(lic.desde),
                "fecha_hasta": iso(lic.hasta),
                "motivo": "",
            }
        )


def escribir_pagos(
    filas: list[tuple[int, dict[str, object]]],
    vinculo: dict[str, str],
    cargos: list[FilaCargo],
    lote: Lote,
) -> None:
    """Cada fila de la planilla de pagos es una boleta histórica y, si se pagó, su pago."""
    registros_de: dict[str, set[int]] = defaultdict(set)
    for _, f in filas:
        if digitos(f.get("REGISTRO")):
            registros_de[texto(f.get("NOMBRES"))].add(int(digitos(f.get("REGISTRO"))))
    for numero, f in filas:
        codigo = f"APD-{numero}"
        nombres = texto(f.get("NOMBRES"))
        registro = digitos(f.get("REGISTRO"))
        vencimiento = una_fecha(f.get("VTO"))
        if not registro:
            registro = _deducir_registro(nombres, vencimiento, registros_de, vinculo, cargos)
            if registro:
                lote.anotar(
                    PAGOS,
                    numero,
                    codigo,
                    "REGISTRO_DEDUCIDO",
                    f"La fila no trae registro: se usa el {registro} de esa persona.",
                )
            else:
                lote.anotar(
                    PAGOS,
                    numero,
                    codigo,
                    "SIN_REGISTRO",
                    "La fila no trae registro y no se pudo deducir: queda observada.",
                )
        mes, anio = digitos(f.get("CUOTA")), digitos(f.get("_"))
        periodo = f"{int(anio):04d}-{int(mes):02d}" if mes and anio and 1 <= int(mes) <= 12 else ""
        pagado = importe(f.get("PAGO"))
        concepto = texto(f.get("CONCEPTO"))
        if pagado is not None and pagado < 0:
            # Importe negativo = crédito a favor del escribano (confirmado por la Caja: surge
            # de una diferencia de inspección a su favor). No es una cuota.
            credito = lote.redondear(PAGOS, numero, f"CRE-{numero}", -pagado)
            if clave_nombre(concepto) != CONCEPTO_INSPECCION:
                lote.anotar(
                    PAGOS,
                    numero,
                    f"CRE-{numero}",
                    "CREDITO_A_CONFIRMAR",
                    f"Importe negativo con concepto «{concepto}»: se toma como crédito, confirmar.",
                )
            lote.archivos["creditos"].append(
                {
                    "codigo_legado": f"CRE-{numero}",
                    "numero_registro": registro,
                    "fecha": iso(una_fecha(f.get("FECHA PAGO")) or vencimiento),
                    "importe": monto(credito),
                    "periodo": periodo,
                    "concepto": concepto[:100],
                }
            )
            continue
        if pagado is None:
            debido = importe(f.get("APORTES"))
            valor = abs(debido) if debido is not None else None
            estado = "IMPAGA"
            if debido is not None and debido < 0:
                lote.anotar(
                    PAGOS,
                    numero,
                    codigo,
                    "IMPAGA_SIGNO_INVERTIDO",
                    "Cuota sin pago con el aporte en negativo: se toma como deuda.",
                )
        else:
            valor, estado = pagado, "PAGADA"
            if pagado == 0:
                lote.anotar(
                    PAGOS,
                    numero,
                    codigo,
                    "PAGO_EN_CERO",
                    "Pago en cero en el origen: revisar qué representa.",
                )
        if valor is not None:
            valor = lote.redondear(PAGOS, numero, codigo, valor)
        lote.archivos["boletas"].append(
            {
                "codigo_legado": codigo,
                "numero_registro": registro,
                "periodo": periodo,
                # El origen no tiene fecha de emisión: se toma el vencimiento.
                "fecha_emision": iso(vencimiento),
                "fecha_vencimiento": iso(vencimiento),
                "importe": monto(valor) if valor is not None else "",
                "estado": estado,
                "numero_boleta": concepto[:50],
            }
        )
        if estado == "PAGADA" and valor is not None and valor > 0:
            lote.archivos["pagos"].append(
                {
                    "codigo_legado": f"PAG-{numero}",
                    "boleta": codigo,
                    "fecha_pago": iso(una_fecha(f.get("FECHA PAGO"))),
                    "importe": monto(valor),
                    "medio": "",
                }
            )


def _deducir_registro(
    nombres: str,
    vencimiento: date | None,
    registros_de: dict[str, set[int]],
    vinculo: dict[str, str],
    cargos: list[FilaCargo],
) -> str:
    if len(registros_de[nombres]) == 1:
        return str(next(iter(registros_de[nombres])))
    persona = vinculo.get(nombres)
    if persona is None or vencimiento is None:
        return ""
    vigentes = {
        c.registro
        for c in cargos
        if c.persona == persona
        and (c.desde is None or c.desde <= vencimiento)
        and (c.hasta is None or vencimiento <= c.hasta)
    }
    return str(vigentes.pop()) if len(vigentes) == 1 else ""


def leer_departamentos(ruta: Path | None) -> dict[int, dict[str, str]]:
    if ruta is None:
        return {}
    contenido = ruta.read_text(encoding="utf-8-sig")
    separador = max((";", ",", "\t"), key=contenido.splitlines()[0].count)
    datos: dict[int, dict[str, str]] = {}
    for fila in csv.DictReader(contenido.splitlines(), delimiter=separador):
        fila = {k.strip().lower(): (v or "").strip() for k, v in fila.items()}
        if fila.get("numero_registro", "").isdigit():
            datos[int(fila["numero_registro"])] = fila
    return datos


def totales_de_origen(filas: list[tuple[int, dict[str, object]]]) -> dict[str, tuple[int, Decimal]]:
    """Totales de la planilla de pagos tal como vienen, sin redondear fila por fila: si la
    extracción pierde una fila o un importe, la cuadratura lo muestra."""
    boletas, pagos, creditos = Decimal("0"), Decimal("0"), Decimal("0")
    cantidad_pagos = cantidad_creditos = 0
    for _, f in filas:
        pagado = importe(f.get("PAGO"))
        if pagado is not None and pagado < 0:
            creditos -= pagado
            cantidad_creditos += 1
        elif pagado is None:
            debido = importe(f.get("APORTES"))
            boletas += abs(debido) if debido is not None else Decimal("0")
        else:
            boletas += pagado
            if pagado > 0:
                pagos += pagado
                cantidad_pagos += 1
    return {
        "boletas": (
            len(filas) - cantidad_creditos,
            boletas.quantize(CENTAVO, rounding=ROUND_HALF_UP),
        ),
        "pagos": (cantidad_pagos, pagos.quantize(CENTAVO, rounding=ROUND_HALF_UP)),
        "creditos": (cantidad_creditos, creditos.quantize(CENTAVO, rounding=ROUND_HALF_UP)),
    }


def extraer(listado: Path, pagos: Path, departamentos: Path | None = None) -> Lote:
    lote = Lote()
    licencias: list[FilaLicencia] = []
    personas, cargos = leer_listado(filas_hoja(listado, "TODOS", 3), lote, licencias)
    filas_pagos = list(filas_hoja(pagos, "aportes", 3))
    lote.origen = totales_de_origen(filas_pagos)
    vinculo = matriculas_desde_pagos(filas_pagos, personas, lote)
    escribir_padron(personas, cargos, leer_departamentos(departamentos), lote)
    escribir_licencias(personas, licencias, lote)
    escribir_pagos(filas_pagos, vinculo, cargos, lote)
    return lote


def _sin_formula(valor: str) -> str:
    from app.modules.reportes.exportar import FORMULA_PREFIJOS

    return f"'{valor}" if valor.startswith(FORMULA_PREFIJOS) else valor


def guardar(lote: Lote, salida: Path) -> None:
    salida.mkdir(parents=True, exist_ok=True)

    def volcar(
        nombre: str, columnas: Iterable[str], filas: list[dict[str, str]], revision: bool = False
    ) -> None:
        # Los archivos de revisión se abren en Excel: un texto que empieza con «=» no se ejecuta.
        if revision:
            filas = [{k: _sin_formula(v) for k, v in f.items()} for f in filas]
        with (salida / nombre).open("w", encoding="utf-8", newline="") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=list(columnas), delimiter=SEPARADOR)
            escritor.writeheader()
            escritor.writerows(filas)

    control = []
    for entidad, columnas in COLUMNAS.items():
        filas = lote.archivos[entidad]
        volcar(f"{entidad}.csv", columnas, filas)
        # Boletas y pagos: lo que trae la planilla. Padrón: las personas y cargos que resultan de
        # unir las filas repetidas (no hay otro total en el origen).
        origen = lote.origen.get(entidad)
        cantidad, total = origen if origen else (len(filas), None)
        control.append(
            {
                "entidad": entidad,
                "filas": str(cantidad),
                "importe": monto(total) if total is not None else "",
            }
        )
    volcar("control.csv", ("entidad", "filas", "importe"), control)
    volcar(
        "extraccion.csv",
        ("fuente", "fila_excel", "codigo_legado", "accion", "motivo"),
        lote.extraccion,
        revision=True,
    )
    volcar(
        "redondeos.csv",
        ("fuente", "fila_excel", "codigo_legado", "original", "redondeado"),
        lote.redondeos,
        revision=True,
    )


def main(argumentos: list[str] | None = None) -> int:
    lector = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lector.add_argument("--listado", type=Path, required=True)
    lector.add_argument("--pagos", type=Path, required=True)
    lector.add_argument("--registros", type=Path)
    lector.add_argument("--salida", type=Path, required=True)
    args = lector.parse_args(argumentos)
    lote = extraer(args.listado, args.pagos, args.registros)
    guardar(lote, args.salida)
    for entidad in COLUMNAS:
        sys.stdout.write(f"{entidad}: {len(lote.archivos[entidad])}\n")
    acciones: dict[str, int] = defaultdict(int)
    for anotacion in lote.extraccion:
        acciones[anotacion["accion"]] += 1
    for accion, cantidad in sorted(acciones.items()):
        sys.stdout.write(f"  {accion}: {cantidad}\n")
    sys.stdout.write(f"importes redondeados: {len(lote.redondeos)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
