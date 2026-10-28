"""Índice del protocolo por foto: cada renglón (una escritura) se vuelve un acto sugerido.

Dos lectores, con la misma salida (`Renglon`, todo como texto tal cual se lee):

- Visión (DeepSeek): el modelo transcribe los renglones a JSON. Lee letra manuscrita y
  columnas; es externo, así que solo se usa con IA_VISION_PROVEEDOR=deepseek.
- OCR local (Tesseract): el texto de la foto se parte en renglones con reglas. Respaldo cuando
  el proveedor externo no está configurado o no responde.

De acá en adelante todo es local y explicable: cada renglón pasa por las mismas reglas que la
minuta (naturaleza, categoría, montos) y por los controles de la DDJJ (período, número ya
declarado). Nada se guarda como acto hasta que la persona lo ratifica (HIC).
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.ddjj.catalog import CategoriaActo, TipoProtocolo
from app.modules.ia import minutas
from app.modules.ia.catalog import NivelAlerta
from app.modules.ia.minutas import NATURALEZAS_ACTA_O_PODER, ContextoMinuta
from app.modules.ia.numeros import monto_ar, plano
from app.modules.ia.resultado import Alerta, Campo, Resultado

MAX_RENGLONES = 200

# Instrucciones al modelo de visión: transcribir, no interpretar. Las reglas de negocio se
# aplican después, localmente.
PROMPT_VISION = """Esta foto es una página del índice del protocolo de una escribanía de \
San Juan, Argentina. Cada renglón es una escritura.

Transcribí TODOS los renglones de escrituras, en el orden en que aparecen, como un arreglo \
JSON. Cada elemento es un objeto con estas claves (todas texto, o null si no se lee):
- "numero": número de escritura.
- "fecha": fecha tal como figura (por ejemplo 05/10/2026).
- "naturaleza": tipo de acto (compraventa, hipoteca, poder, acta…).
- "partes": otorgantes tal como figuran.
- "folio": número de folio.
- "monto": monto o precio tal como figura, con sus puntos y comas.
- "protocolo": "auxiliar" si el renglón lo indica; si no, null.

No inventes datos ni completes lo que no se ve: si un dato falta o es ilegible, null. No \
incluyas encabezados ni totales. Respondé solo el JSON, sin explicaciones."""


@dataclass(frozen=True)
class Renglon:
    """Un renglón del índice tal como se leyó (sin interpretar)."""

    numero: str | None = None
    fecha: str | None = None
    naturaleza: str | None = None
    partes: str | None = None
    folio: str | None = None
    monto: str | None = None
    protocolo: str | None = None
    # Foto de la que salió (1, 2…), para ubicarlo al revisar.
    foto: int = 1


class RespuestaInvalidaError(ValueError):
    pass


# Ningún dato de un renglón necesita más (la naturaleza del acto admite 300).
MAX_CARACTERES_CAMPO = 300
# Base imponible: hasta 16 enteros y 2 decimales (Numeric(18,2)).
MAX_CIFRAS_MONTO = 18


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()[:MAX_CARACTERES_CAMPO]
    return texto or None


def renglones_de_vision(respuesta: str, foto: int) -> list[Renglon]:
    """Arreglo JSON del modelo → renglones. Tolera el JSON envuelto en un bloque de código.
    Los números se leen como texto: nunca pasan por float."""
    texto = respuesta.strip()
    bloque = re.search(r"```(?:json)?\s*(.*?)```", texto, re.DOTALL)
    if bloque:
        texto = bloque.group(1).strip()
    inicio, fin = texto.find("["), texto.rfind("]")
    if inicio == -1 or fin < inicio:
        raise RespuestaInvalidaError("La lectura no devolvió una lista de renglones.")
    try:
        # Los números quedan como texto, tal cual se leyeron: sin float ni conversiones que
        # puedan fallar con cifras desmesuradas.
        datos = json.loads(texto[inicio : fin + 1], parse_float=str, parse_int=str)
    except ValueError as exc:
        raise RespuestaInvalidaError("La lectura no devolvió JSON válido.") from exc
    if not isinstance(datos, list):
        raise RespuestaInvalidaError("La lectura no devolvió una lista de renglones.")
    renglones = []
    for item in datos[:MAX_RENGLONES]:
        if not isinstance(item, dict):
            continue
        renglon = Renglon(
            numero=_texto(item.get("numero")),
            fecha=_texto(item.get("fecha")),
            naturaleza=_texto(item.get("naturaleza")),
            partes=_texto(item.get("partes")),
            folio=_texto(item.get("folio")),
            monto=_texto(item.get("monto")),
            protocolo=_texto(item.get("protocolo")),
            foto=foto,
        )
        if renglon.numero or renglon.naturaleza:
            renglones.append(renglon)
    return renglones


# Renglón del índice en texto OCR: número, fecha y el resto (naturaleza, partes, folio, monto).
_RENGLON_OCR = re.compile(
    r"^\s*(?:n[°º]?\s*)?(\d{1,6})[\s.|)-]+(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})\s+(.*)$",
    re.IGNORECASE,
)
_MONTO_OCR = re.compile(r"\$?\s*(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+,\d{2})\s*$")
_FOLIO_OCR = re.compile(r"\s(\d{1,5})\s*$")


def renglones_de_ocr(texto: str, foto: int) -> list[Renglon]:
    """Texto OCR de la foto → renglones. Solo toma las líneas que empiezan con número y fecha;
    el resto de la línea se parte en naturaleza (y partes), folio y monto desde el final."""
    renglones = []
    for linea in texto.splitlines():
        m = _RENGLON_OCR.match(linea)
        if not m:
            continue
        resto = m.group(3).rstrip(" -|")
        monto = None
        if mm := _MONTO_OCR.search(resto):
            monto, resto = mm.group(1), resto[: mm.start()].rstrip(" -|$")
        folio = None
        if mf := _FOLIO_OCR.search(resto):
            folio, resto = mf.group(1), resto[: mf.start()].rstrip()
        # Naturaleza y partes suelen ir separadas por dos o más espacios.
        columnas = re.split(r"\s{2,}|\s\|\s", resto.strip(), maxsplit=1)
        renglones.append(
            Renglon(
                numero=m.group(1),
                fecha=m.group(2),
                naturaleza=columnas[0] or None,
                partes=columnas[1] if len(columnas) > 1 else None,
                folio=folio,
                monto=monto,
                foto=foto,
            )
        )
        if len(renglones) >= MAX_RENGLONES:
            break
    return renglones


# --------------------------------------------------------------------------- renglón → acto


def _d(valor: str) -> Decimal:
    return Decimal(valor)


def _numero(r: Renglon, confianza: Decimal) -> Campo:
    if r.numero and (m := re.search(r"\d{1,6}", r.numero)) and int(m.group(0)) > 0:
        return Campo(str(int(m.group(0))), confianza, "Número de escritura del índice.", r.numero)
    return Campo(None, _d("0"), "No se leyó el número de escritura.")


def _fecha(r: Renglon, ctx: ContextoMinuta, confianza: Decimal, alertas: list[Alerta]) -> Campo:
    m = re.fullmatch(r"\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\s*", r.fecha or "")
    if not m:
        return Campo(None, _d("0"), "No se leyó la fecha del acto.")
    dia, mes, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if anio < 100:
        anio += 2000
    try:
        fecha = date(anio, mes, dia)
    except ValueError:
        return Campo(None, _d("0"), "La fecha leída no existe.", r.fecha)
    if not ctx.periodo_desde <= fecha <= ctx.periodo_hasta:
        alertas.append(
            Alerta(
                "FECHA_FUERA_DEL_PERIODO",
                NivelAlerta.ADVERTENCIA,
                f"La fecha {fecha:%d/%m/%Y} no es del período de esta declaración.",
                r.fecha,
            )
        )
    return Campo(fecha.isoformat(), confianza, "Fecha del índice.", r.fecha)


def _naturaleza(r: Renglon, confianza: Decimal) -> Campo:
    if not r.naturaleza:
        return Campo(None, _d("0"), "No se leyó la naturaleza del acto.")
    # Mismas formas canónicas que la minuta ("compra-venta" → "Compraventa").
    canonica = minutas.naturaleza_canonica(plano(r.naturaleza))
    # Las partes ayudan a revisar, pero no se guardan (solo viajan en la respuesta).
    evidencia = f"{r.naturaleza} · {r.partes}" if r.partes else r.naturaleza
    if canonica:
        return Campo(canonica, confianza, "Naturaleza del índice.", evidencia)
    return Campo(
        r.naturaleza[:300], confianza * _d("0.8"), "Naturaleza tal como figura.", evidencia
    )


def _folio(r: Renglon, confianza: Decimal) -> Campo:
    if r.folio and (m := re.search(r"\d{1,6}", r.folio)) and int(m.group(0)) > 0:
        return Campo(str(int(m.group(0))), confianza, "Folio del índice.", r.folio)
    return Campo(None, _d("0"), "Sin folio en el índice.")


def _monto(r: Renglon, confianza: Decimal) -> Campo:
    if not r.monto:
        return Campo(None, _d("0"), "Sin monto en el índice.")
    cifras = re.sub(r"[^\d.,]", "", r.monto)
    if not re.search(r"\d", cifras):
        return Campo(None, _d("0"), "Sin monto en el índice.", r.monto)
    entero = re.split(r",", cifras.replace(".", ""), maxsplit=1)[0]
    if len(entero) > MAX_CIFRAS_MONTO - 2 or len(re.sub(r"\D", "", cifras)) > MAX_CIFRAS_MONTO:
        return Campo(None, _d("0"), "El monto leído es demasiado largo.", r.monto[:100])
    valor = monto_ar(cifras)
    if valor is None or valor <= 0:
        return Campo(None, _d("0"), "No se pudo leer el monto.", r.monto)
    return Campo(f"{valor:.2f}", confianza, "Monto del índice.", r.monto)


def _protocolo(r: Renglon) -> Campo:
    if r.protocolo and "aux" in plano(r.protocolo):
        return Campo(
            TipoProtocolo.AUXILIAR.value, _d("0.80"), "El renglón indica protocolo auxiliar."
        )
    return Campo(
        TipoProtocolo.GENERAL.value, _d("0.60"), "Protocolo general (el índice no indica otro)."
    )


def _categoria(naturaleza: Campo, monto: Campo) -> Campo:
    if naturaleza.valor in NATURALEZAS_ACTA_O_PODER:
        return Campo(
            CategoriaActo.ACTA_O_PODER.value,
            _d("0.75"),
            f"Por la naturaleza ({naturaleza.valor}): aporte fijo por acto.",
        )
    if monto.valor is not None:
        return Campo(
            CategoriaActo.ESCRITURA_CON_VALOR.value,
            _d("0.70"),
            "El renglón tiene monto: escritura con valor.",
        )
    return Campo(
        CategoriaActo.OTRO_ACTO.value,
        _d("0.40"),
        "Sin monto ni naturaleza de acta o poder: verificá la categoría.",
    )


def a_resultado(r: Renglon, ctx: ContextoMinuta, *, confianza: Decimal) -> Resultado:
    """Un renglón → campos de un acto, con las mismas claves que la minuta.

    `confianza` es la del lector (la visión no informa una por dato): las reglas derivadas
    (categoría, protocolo) llevan la suya."""
    alertas: list[Alerta] = []
    naturaleza = _naturaleza(r, confianza)
    monto = _monto(r, confianza)
    categoria = _categoria(naturaleza, monto)
    if categoria.valor == CategoriaActo.ESCRITURA_CON_VALOR.value:
        base = monto
    elif monto.valor is not None:
        # Solo las escrituras con valor llevan base imponible (misma regla que la carga manual).
        base = Campo("0.00", _d("0.60"), "La categoría sugerida no lleva base imponible.")
        alertas.append(
            Alerta(
                "MONTO_SIN_VALOR",
                NivelAlerta.AVISO,
                "El renglón trae un monto pero la naturaleza es de acta o poder: revisá la "
                "categoría.",
                r.monto,
            )
        )
    else:
        base = Campo("0.00", _d("0.70"), "La categoría sugerida no lleva base imponible.")
    campos = {
        "tipo_protocolo": _protocolo(r),
        "numero_escritura": _numero(r, confianza),
        "folio": _folio(r, confianza),
        "fecha_acto": _fecha(r, ctx, confianza, alertas),
        "naturaleza": naturaleza,
        "categoria": categoria,
        "base_imponible": base,
    }
    numero, protocolo = campos["numero_escritura"].valor, campos["tipo_protocolo"].valor
    if numero is not None and protocolo is not None and (protocolo, int(numero)) in ctx.declarados:
        alertas.append(
            Alerta(
                "NUMERO_YA_DECLARADO",
                NivelAlerta.ADVERTENCIA,
                f"La escritura N° {numero} del protocolo {protocolo.lower()} ya está declarada "
                "este año.",
            )
        )
    for clave, texto in (("numero_escritura", "el número"), ("fecha_acto", "la fecha")):
        if campos[clave].valor is None:
            alertas.append(
                Alerta(
                    "DATO_ILEGIBLE",
                    NivelAlerta.ADVERTENCIA,
                    f"No se pudo leer {texto}: completalo mirando el libro.",
                )
            )
    return Resultado(campos, alertas)
