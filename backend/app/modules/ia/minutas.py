"""Extracción asistida de un acto a partir del texto de una minuta o borrador de escritura.

Motor de reglas explicable (módulo 10 §1.1, XAI): cada campo propuesto trae la regla que lo
produjo, una confianza y el fragmento del texto que lo respalda. Las alertas señalan
inconsistencias para que el escribano las revise. Nada de esto se guarda como acto: es una
sugerencia hasta que una persona la ratifica.

Función pura (sin base de datos ni red): recibe el texto y el contexto de la DDJJ.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.common.cuit import InvalidCuitError, normalize_cuit
from app.common.money import format_pesos
from app.modules.ddjj.catalog import CategoriaActo, TipoProtocolo
from app.modules.ia.catalog import NivelAlerta
from app.modules.ia.numeros import (
    MONTO_CIFRAS,
    es_palabra_numero,
    monto_ar,
    monto_en_letras,
    palabras_a_entero,
    plano,
)
from app.modules.ia.resultado import Alerta, Campo, Resultado
from app.modules.padron.catalog import Cargo

MAX_CARACTERES = 200_000
MIN_CARACTERES_UTILES = 120
CONTEXTO_EVIDENCIA = 50

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_MES = "(" + "|".join(MESES) + ")"

# Naturalezas reconocidas por palabra clave (de la más específica a la más general). La lista
# es orientativa para sugerir: el escribano define la naturaleza al ratificar.
NATURALEZAS: tuple[tuple[str, str], ...] = (
    ("cancelacion de hipoteca", "Cancelación de hipoteca"),
    ("constitucion de hipoteca", "Hipoteca"),
    ("hipoteca", "Hipoteca"),
    ("compraventa", "Compraventa"),
    ("compra-venta", "Compraventa"),
    ("compra venta", "Compraventa"),
    ("donacion", "Donación"),
    ("permuta", "Permuta"),
    ("cesion de derechos", "Cesión de derechos"),
    ("division de condominio", "División de condominio"),
    ("usufructo", "Usufructo"),
    ("fideicomiso", "Fideicomiso"),
    ("constitucion de sociedad", "Constitución de sociedad"),
    ("afectacion a vivienda", "Afectación a vivienda"),
    ("protocolizacion", "Protocolización"),
    ("testamento", "Testamento"),
    ("revocacion de poder", "Revocación de poder"),
    ("poder especial", "Poder especial"),
    ("poder general", "Poder general"),
    ("acta de constatacion", "Acta de constatación"),
    ("acta de notificacion", "Acta de notificación"),
    ("venta", "Compraventa"),
    ("poder", "Poder"),
    ("acta", "Acta"),
)
# Sin base imponible por su naturaleza (aporte fijo por acto).
NATURALEZAS_ACTA_O_PODER = frozenset(
    {
        "Revocación de poder",
        "Poder especial",
        "Poder general",
        "Poder",
        "Acta de constatación",
        "Acta de notificación",
        "Acta",
    }
)


@dataclass(frozen=True)
class Candidato:
    """Escribano con cargo en el registro durante el período de la DDJJ."""

    escribano_id: uuid.UUID
    apellido: str
    nombre: str
    matricula: int
    # Lugar en el equipo del registro: TITULAR, ADSCRIPTO o SUPLENTE_INTERINO ("a cargo").
    cargo: str


@dataclass(frozen=True)
class ContextoMinuta:
    periodo_desde: date
    periodo_hasta: date
    hoy: date
    registro_numero: int
    candidatos: tuple[Candidato, ...]
    # (tipo de protocolo, número de escritura) ya declarados en la DDJJ.
    declarados: frozenset[tuple[str, int]] = frozenset()


def _d(valor: str) -> Decimal:
    return Decimal(valor)


def _cita(texto: str, inicio: int, fin: int) -> str:
    """Fragmento de respaldo: lo encontrado con un poco de contexto, en una línea."""
    desde = max(0, inicio - CONTEXTO_EVIDENCIA)
    hasta = min(len(texto), fin + CONTEXTO_EVIDENCIA)
    fragmento = " ".join(texto[desde:hasta].split())
    return ("…" if desde > 0 else "") + fragmento + ("…" if hasta < len(texto) else "")


def _sin_dato(regla: str) -> Campo:
    return Campo(None, _d("0"), regla)


# --------------------------------------------------------------------------- número y folio

_NUMERO_ESCRITURA = re.compile(
    r"escritura\s+(?:publica\s+)?(?:n\S{1,2}mero|nro\.?|n\s?[°º]\.?|no\.)\s*:?\s*"
    r"|escritura\s+(?=[0-9])"
)


def _numero(texto: str, p: str, alertas: list[Alerta]) -> Campo:
    m = _NUMERO_ESCRITURA.search(p)
    if m is None:
        return _sin_dato("No se encontró «Escritura número …».")
    ventana = p[m.end() : m.end() + 120]
    cifras = re.search(r"\(?\s*([0-9]{1,6})\s*\)?", ventana)
    hasta_cifras = ventana[: cifras.start()] if cifras else ventana
    # Las letras van antes de las cifras ("CIENTO VEINTE (120)") y terminan en un no-número.
    palabras = []
    for palabra in re.findall(r"[a-z]+|[^a-z\s]", hasta_cifras):
        if not es_palabra_numero(palabra):
            break
        palabras.append(palabra)
    letras = palabras_a_entero(" ".join(palabras))
    fin = m.end() + (cifras.end() if cifras else len(" ".join(palabras)))
    cita = _cita(texto, m.start(), fin)
    n_cifras = int(cifras.group(1)) if cifras and cifras.start() <= 90 else None
    if n_cifras is not None and letras is not None:
        if n_cifras == letras:
            return Campo(str(n_cifras), _d("0.95"), "Número en cifras y en letras coinciden.", cita)
        alertas.append(
            Alerta(
                "NUMERO_LETRAS_DISTINTO",
                NivelAlerta.ADVERTENCIA,
                f"El número de escritura en cifras ({n_cifras}) no coincide con el escrito en "
                f"letras ({letras}).",
                cita,
            )
        )
        return Campo(
            str(n_cifras), _d("0.40"), "Se tomó el número en cifras; difiere de las letras.", cita
        )
    if n_cifras is not None:
        return Campo(str(n_cifras), _d("0.85"), "Número de escritura en cifras.", cita)
    if letras is not None and 0 < letras <= 1_000_000:
        return Campo(str(letras), _d("0.75"), "Número de escritura escrito en letras.", cita)
    return _sin_dato("Se encontró «Escritura número» pero no un número legible.")


_FOLIO = re.compile(r"\bfolios?\s*(?:n\S{1,2}mero|nro\.?|n\s?[°º]\.?)?\s*:?\s*([0-9]{1,6})\b")


def _folio(texto: str, p: str) -> Campo:
    m = _FOLIO.search(p)
    if m is None:
        return _sin_dato("No se encontró el folio.")
    return Campo(
        str(int(m.group(1))), _d("0.85"), "Folio en cifras.", _cita(texto, m.start(), m.end())
    )


def _protocolo(texto: str, p: str) -> Campo:
    m = re.search(r"protocolo\s+auxiliar", p)
    if m:
        return Campo(
            TipoProtocolo.AUXILIAR.value,
            _d("0.80"),
            "El texto menciona el protocolo auxiliar.",
            _cita(texto, m.start(), m.end()),
        )
    return Campo(
        TipoProtocolo.GENERAL.value,
        _d("0.60"),
        "Sin mención del protocolo auxiliar: se propone el general.",
    )


# --------------------------------------------------------------------------- fecha

_FECHA_LETRAS = re.compile(
    r"(?:a\s+los|al)\s+([a-z\s]{3,40}?)\s+d\S{1,2}as?\s+del\s+mes\s+de\s+" + _MES + r"\s+"
    r"(?:del?\s+(?:a\S{0,2}o|corriente\s+a\S{0,2}o)\s+)?(?:de\s+)?([a-z\s]{8,60}|[0-9]{4})"
)
_FECHA_MIXTA = re.compile(
    r"\b([0-9]{1,2})\s+(?:de\s+|dias\s+del\s+mes\s+de\s+)"
    + _MES
    + r"\s+del?\s+(?:ano\s+)?([0-9]{4})"
)
_FECHA_NUMERICA = re.compile(r"\b([0-9]{1,2})[/.-]([0-9]{1,2})[/.-]([0-9]{4})\b")


def _anio_en_letras(texto: str) -> int | None:
    palabras = []
    for palabra in re.findall(r"[a-z]+", texto):
        if not es_palabra_numero(palabra):
            break
        palabras.append(palabra)
    return palabras_a_entero(" ".join(palabras))


def _construir(dia: int | None, mes: int, anio: int | None) -> date | None:
    if dia is None or anio is None:
        return None
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def _fechas(p: str) -> list[tuple[int, int, date, str]]:
    """Fechas encontradas: (inicio, fin, fecha, regla)."""
    halladas: list[tuple[int, int, date, str]] = []
    for m in _FECHA_LETRAS.finditer(p):
        anio_txt = m.group(3)
        anio = int(anio_txt) if anio_txt.isdigit() else _anio_en_letras(anio_txt)
        fecha = _construir(palabras_a_entero(m.group(1)), MESES[m.group(2)], anio)
        if fecha:
            halladas.append((m.start(), m.end(), fecha, "Fecha escrita en letras."))
    for m in _FECHA_MIXTA.finditer(p):
        fecha = _construir(int(m.group(1)), MESES[m.group(2)], int(m.group(3)))
        if fecha:
            halladas.append((m.start(), m.end(), fecha, "Fecha con día y año en cifras."))
    for m in _FECHA_NUMERICA.finditer(p):
        fecha = _construir(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if fecha:
            halladas.append((m.start(), m.end(), fecha, "Fecha en formato dd/mm/aaaa."))
    return sorted(halladas, key=lambda h: h[0])


def _fecha(texto: str, p: str, ctx: ContextoMinuta, alertas: list[Alerta]) -> Campo:
    halladas = _fechas(p)
    if not halladas:
        alertas.append(
            Alerta(
                "FECHA_NO_ENCONTRADA",
                NivelAlerta.AVISO,
                "No se encontró la fecha del acto: completala al revisar.",
            )
        )
        return _sin_dato("No se encontró una fecha.")
    # La primera fecha del texto suele ser la del otorgamiento; las siguientes, de nacimientos,
    # títulos antecedentes o certificados.
    inicio, fin, fecha, regla = halladas[0]
    cita = _cita(texto, inicio, fin)
    confianza = _d("0.85") if "letras" in regla or "cifras" in regla else _d("0.70")
    if fecha > ctx.hoy:
        alertas.append(
            Alerta(
                "FECHA_FUTURA",
                NivelAlerta.ADVERTENCIA,
                f"La fecha del acto ({fecha:%d/%m/%Y}) es posterior a hoy.",
                cita,
            )
        )
        confianza = _d("0.40")
    elif not ctx.periodo_desde <= fecha <= ctx.periodo_hasta:
        alertas.append(
            Alerta(
                "FECHA_FUERA_DE_PERIODO",
                NivelAlerta.ADVERTENCIA,
                f"La fecha del acto ({fecha:%d/%m/%Y}) no está dentro del período de la "
                "declaración: el acto va en la DDJJ de su mes.",
                cita,
            )
        )
        confianza = _d("0.50")
    return Campo(fecha.isoformat(), confianza, regla, cita)


# --------------------------------------------------------------------------- naturaleza


def _naturaleza(texto: str, p: str) -> Campo:
    mejor: tuple[int, int, str, int] | None = None  # (inicio, -longitud, naturaleza, fin)
    for clave, nombre in NATURALEZAS:
        m = re.search(r"\b" + re.escape(clave) + r"\b", p)
        if m is None:
            continue
        candidato = (m.start(), -len(clave), nombre, m.end())
        if mejor is None or candidato[:2] < mejor[:2]:
            mejor = candidato
    if mejor is None:
        return _sin_dato("No se reconoció la naturaleza del acto.")
    inicio, _, nombre, fin = mejor
    confianza = _d("0.80") if inicio < 600 else _d("0.60")
    return Campo(
        nombre,
        confianza,
        "Palabra clave de la naturaleza (la primera que aparece en el texto).",
        _cita(texto, inicio, fin),
    )


# --------------------------------------------------------------------------- monto

_MONTO = re.compile(r"(?:\$|\bpesos\b)\s*(" + MONTO_CIFRAS + r")")
_MONEDA_EXTRANJERA = re.compile(r"\bu\s?\$\s?s\b|\bus\$|\busd\b|\bdolares\b|\beuros?\b")
_CLAVE_MONTO = re.compile(r"precio|valuacion|valor|monto|suma|importe|capital")
# "(pesos cuarenta y cinco millones)" o "pesos cuarenta y cinco millones ($ 45.000.000)".
_LETRAS_MONTO = re.compile(r"\bpesos\s+([a-z\s]{4,200}?)(?=[(),.;:$]|\s+con\s+[0-9]|$)")


def _letras_cercanas(p: str, inicio: int, fin: int) -> Decimal | None:
    ventana_inicio = max(0, inicio - 220)
    for m in _LETRAS_MONTO.finditer(p, ventana_inicio, min(len(p), fin + 220)):
        resto = p[m.end() : m.end() + 40]
        centavos = re.match(r"\s*con\s+([a-z\s]+?)\s+centavos", resto)
        letras = m.group(1) + (f" con {centavos.group(1)} centavos" if centavos else "")
        valor = monto_en_letras(letras)
        if valor is not None:
            return valor
    return None


def _monto(texto: str, p: str, alertas: list[Alerta]) -> Campo:
    hallados = []
    for m in _MONTO.finditer(p):
        valor = monto_ar(m.group(1))
        if valor is not None and valor > 0:
            previo = p[max(0, m.start() - 80) : m.start()]
            hallados.append((m, valor, bool(_CLAVE_MONTO.search(previo))))
    extranjera = _MONEDA_EXTRANJERA.search(p)
    if extranjera:
        alertas.append(
            Alerta(
                "MONEDA_EXTRANJERA",
                NivelAlerta.ADVERTENCIA,
                "El texto menciona moneda extranjera: la base imponible se declara en pesos "
                "según la normativa de la Caja.",
                _cita(texto, extranjera.start(), extranjera.end()),
            )
        )
    if not hallados:
        return _sin_dato("No se encontró un monto en pesos.")
    distintos = sorted({v for _, v, _ in hallados})
    if len(distintos) > 1:
        alertas.append(
            Alerta(
                "VARIOS_MONTOS",
                NivelAlerta.AVISO,
                "El texto tiene varios montos ("
                + ", ".join(format_pesos(v) for v in distintos[:5])
                + "): verificá cuál es la base imponible.",
            )
        )
    m, valor, con_clave = next((h for h in hallados if h[2]), hallados[0])
    cita = _cita(texto, m.start(), m.end())
    letras = _letras_cercanas(p, m.start(), m.end())
    if letras is not None and letras != valor:
        alertas.append(
            Alerta(
                "MONTO_LETRAS_DISTINTO",
                NivelAlerta.ADVERTENCIA,
                f"El monto en cifras ({format_pesos(valor)}) no coincide con el escrito en "
                f"letras ({format_pesos(letras)}).",
                cita,
            )
        )
        return Campo(f"{valor:.2f}", _d("0.35"), "Monto en cifras; difiere de las letras.", cita)
    if letras is not None:
        return Campo(f"{valor:.2f}", _d("0.90"), "Monto en cifras y en letras coinciden.", cita)
    if con_clave:
        return Campo(f"{valor:.2f}", _d("0.75"), "Monto junto a «precio», «valor» o «suma».", cita)
    return Campo(f"{valor:.2f}", _d("0.50"), "Primer monto en pesos del texto.", cita)


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
            "El acto tiene un monto en pesos: escritura con valor.",
        )
    return Campo(
        CategoriaActo.OTRO_ACTO.value,
        _d("0.40"),
        "Sin monto ni naturaleza de acta o poder: verificá la categoría.",
    )


# --------------------------------------------------------------------------- escribano


# Cómo se presenta el autorizante: "escribana titular del Registro…", "adscripto al registro…",
# "a cargo del Registro…". El equipo del registro son el titular, los adscriptos y el a cargo.
_CARGO_EN_TEXTO = re.compile(
    r"\b(titular|adscript[oa]|a\s+cargo|suplente|interin[oa])\s+(?:del|al|de\s+este)\s+registro"
)
CARGO_TEXTO = {
    Cargo.TITULAR.value: "titular",
    Cargo.ADSCRIPTO.value: "adscripto",
    Cargo.SUPLENTE_INTERINO.value: "a cargo",
}


def _cargo_mencionado(p: str) -> tuple[str, re.Match[str]] | None:
    m = _CARGO_EN_TEXTO.search(p)
    if m is None:
        return None
    palabra = m.group(1)
    if palabra == "titular":
        return Cargo.TITULAR.value, m
    if palabra.startswith("adscript"):
        return Cargo.ADSCRIPTO.value, m
    return Cargo.SUPLENTE_INTERINO.value, m


def _identificado(
    texto: str,
    c: Candidato,
    confianza: str,
    regla: str,
    cita: str | None,
    mencion: tuple[str, re.Match[str]] | None,
    alertas: list[Alerta],
) -> Campo:
    if mencion is not None and mencion[0] != c.cargo:
        alertas.append(
            Alerta(
                "CARGO_DISTINTO",
                NivelAlerta.ADVERTENCIA,
                f"La minuta presenta al autorizante como {CARGO_TEXTO[mencion[0]]} del registro y "
                f"{c.apellido}, {c.nombre} figura en el padrón como {CARGO_TEXTO[c.cargo]}.",
                _cita(texto, mencion[1].start(), mencion[1].end()),
            )
        )
        confianza = "0.50"
    return Campo(str(c.escribano_id), _d(confianza), regla, cita)


def _escribano(texto: str, p: str, ctx: ContextoMinuta, alertas: list[Alerta]) -> Campo:
    mencion = _cargo_mencionado(p)
    for m in re.finditer(
        r"matr\S{1,2}cula\s*(?:profesional\s*)?(?:n\S{1,2}mero|nro\.?|n\s?[°º]\.?)?\s*:?\s*([0-9]{1,6})",
        p,
    ):
        numero = int(m.group(1))
        for c in ctx.candidatos:
            if c.matricula == numero:
                return _identificado(
                    texto,
                    c,
                    "0.90",
                    "Por la matrícula que menciona el texto.",
                    _cita(texto, m.start(), m.end()),
                    mencion,
                    alertas,
                )
    por_apellido = []
    for c in ctx.candidatos:
        nombrado = re.search(r"\b" + re.escape(plano(c.apellido)) + r"\b", p)
        if nombrado:
            por_apellido.append((c, nombrado))
    if len(por_apellido) == 1:
        c, m = por_apellido[0]
        return _identificado(
            texto,
            c,
            "0.75",
            "Por el apellido que menciona el texto, entre quienes tienen cargo en el registro.",
            _cita(texto, m.start(), m.end()),
            mencion,
            alertas,
        )
    # Sin nombre que decida: el cargo con que se presenta el autorizante desempata dentro del
    # equipo (entre los nombrados, o entre todos si no se nombró a ninguno).
    entre = [c for c, _ in por_apellido] or list(ctx.candidatos)
    if mencion is not None:
        con_cargo = [c for c in entre if c.cargo == mencion[0]]
        if len(con_cargo) == 1:
            c = con_cargo[0]
            return Campo(
                str(c.escribano_id),
                _d("0.60"),
                f"Por el cargo con que se presenta el autorizante ({CARGO_TEXTO[c.cargo]} del "
                "registro).",
                _cita(texto, mencion[1].start(), mencion[1].end()),
            )
    if not por_apellido and len(ctx.candidatos) == 1:
        c = ctx.candidatos[0]
        return _identificado(
            texto,
            c,
            "0.50",
            "Único escribano con cargo en el registro en el período.",
            None,
            mencion,
            alertas,
        )
    alertas.append(
        Alerta(
            "ESCRIBANO_NO_IDENTIFICADO",
            NivelAlerta.AVISO,
            "No se pudo identificar con certeza al escribano autorizante dentro del equipo del "
            "registro (titular, adscriptos y a cargo): elegilo al revisar.",
        )
    )
    return _sin_dato("No se identificó al escribano autorizante.")


# --------------------------------------------------------------------------- validaciones

_CUIT = re.compile(r"\b(20|23|24|27|30|33|34)[-\s.]?([0-9]{8})[-\s.]?([0-9])\b")
_REGISTRO = re.compile(
    r"registro\s+(?:notarial\s+)?(?:n\S{1,2}mero|nro\.?|n\s?[°º]\.?)\s*:?\s*([0-9]{1,4})"
)


def _validaciones(
    texto: str, p: str, ctx: ContextoMinuta, campos: dict[str, Campo]
) -> list[Alerta]:
    alertas: list[Alerta] = []
    for m in _CUIT.finditer(p):
        try:
            normalize_cuit("".join(m.groups()))
        except InvalidCuitError:
            alertas.append(
                Alerta(
                    "CUIT_INVALIDO",
                    NivelAlerta.ADVERTENCIA,
                    f"El CUIT/CUIL {m.group(0)} no tiene un dígito verificador válido.",
                    _cita(texto, m.start(), m.end()),
                )
            )
    menor = re.search(r"menor\s+de\s+edad", p)
    if menor and not re.search(r"represent|tutor|patria\s+potestad|responsabilidad\s+parental", p):
        alertas.append(
            Alerta(
                "MENOR_SIN_REPRESENTACION",
                NivelAlerta.ADVERTENCIA,
                "Se menciona a un menor de edad sin una cláusula de representación legal o tutela.",
                _cita(texto, menor.start(), menor.end()),
            )
        )
    for m in _REGISTRO.finditer(p):
        if int(m.group(1)) != ctx.registro_numero:
            alertas.append(
                Alerta(
                    "REGISTRO_DISTINTO",
                    NivelAlerta.ADVERTENCIA,
                    f"El texto menciona el registro N° {int(m.group(1))} y la declaración es del "
                    f"registro N° {ctx.registro_numero}.",
                    _cita(texto, m.start(), m.end()),
                )
            )
            break
    numero, protocolo = campos["numero_escritura"].valor, campos["tipo_protocolo"].valor
    if numero is not None and protocolo is not None and (protocolo, int(numero)) in ctx.declarados:
        alertas.append(
            Alerta(
                "NUMERO_YA_DECLARADO",
                NivelAlerta.ADVERTENCIA,
                f"La escritura N° {numero} del protocolo {protocolo.lower()} ya está declarada en "
                "esta DDJJ.",
            )
        )
    return alertas


# --------------------------------------------------------------------------- entrada


def extraer(texto: str, ctx: ContextoMinuta) -> Resultado:
    texto = texto[:MAX_CARACTERES]
    p = plano(texto)
    alertas: list[Alerta] = []
    if len(texto.strip()) < MIN_CARACTERES_UTILES:
        alertas.append(
            Alerta(
                "TEXTO_ESCASO",
                NivelAlerta.AVISO,
                "Se leyó muy poco texto del documento: revisá que el archivo sea legible.",
            )
        )
    naturaleza = _naturaleza(texto, p)
    monto = _monto(texto, p, alertas)
    categoria = _categoria(naturaleza, monto)
    sin_monto = monto.valor is None and naturaleza.valor is not None
    if sin_monto and naturaleza.valor not in NATURALEZAS_ACTA_O_PODER:
        alertas.append(
            Alerta(
                "MONTO_NO_ENCONTRADO",
                NivelAlerta.AVISO,
                "No se encontró el monto de la operación: si es una escritura con valor, "
                "cargá la base imponible.",
            )
        )
    if categoria.valor != CategoriaActo.ESCRITURA_CON_VALOR.value:
        # Solo las escrituras con valor llevan base imponible (misma regla que la carga manual).
        monto = Campo("0.00", _d("0.70"), "La categoría sugerida no lleva base imponible.")
    campos = {
        "escribano_id": _escribano(texto, p, ctx, alertas),
        "tipo_protocolo": _protocolo(texto, p),
        "numero_escritura": _numero(texto, p, alertas),
        "folio": _folio(texto, p),
        "fecha_acto": _fecha(texto, p, ctx, alertas),
        "naturaleza": naturaleza,
        "categoria": categoria,
        "base_imponible": monto,
    }
    alertas += _validaciones(texto, p, ctx, campos)
    return Resultado(campos, alertas)
