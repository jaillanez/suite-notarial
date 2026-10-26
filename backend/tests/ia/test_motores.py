"""Motores asistenciales sin base de datos: números en letras, minutas y DNI."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.ia import dni
from app.modules.ia.minutas import Candidato, ContextoMinuta, extraer
from app.modules.ia.numeros import monto_ar, monto_en_letras, palabras_a_entero, plano

TITULAR = Candidato(uuid.uuid4(), "Albarracín", "María", 456, "TITULAR")
ADSCRIPTO = Candidato(uuid.uuid4(), "Quiroga", "Pedro", 789, "ADSCRIPTO")
A_CARGO = Candidato(uuid.uuid4(), "Sánchez", "Laura", 321, "SUPLENTE_INTERINO")


def ctx(
    *candidatos: Candidato, declarados: frozenset[tuple[str, int]] = frozenset()
) -> ContextoMinuta:
    return ContextoMinuta(
        periodo_desde=date(2026, 9, 1),
        periodo_hasta=date(2026, 9, 30),
        hoy=date(2026, 10, 23),
        registro_numero=12,
        candidatos=candidatos or (TITULAR,),
        declarados=declarados,
    )


def texto(**c: str) -> str:
    d = {
        "numero": "CIENTO VEINTE (120)",
        "fecha": "a los catorce días del mes de septiembre del año dos mil veintiséis",
        "autorizante": "MARÍA ALBARRACÍN, Escribana titular del Registro Notarial número 12, "
        "matrícula 456",
        "naturaleza": "COMPRAVENTA",
        "precio": "PESOS CUARENTA Y CINCO MILLONES ($ 45.000.000,00)",
        "extra": "",
        **c,
    }
    return (
        f"ESCRITURA NÚMERO {d['numero']}. FOLIO 345. {d['naturaleza']}. En la Ciudad de San "
        f"Juan, {d['fecha']}, ante mí, {d['autorizante']}, comparecen los otorgantes. "
        f"{d['extra']} Dicen que celebran el acto por el precio total de {d['precio']}."
    )


def valores(t: str, c: ContextoMinuta | None = None) -> dict[str, str | None]:
    return {k: v.valor for k, v in extraer(t, c or ctx()).campos.items()}


def codigos(t: str, c: ContextoMinuta | None = None) -> set[str]:
    return {a.codigo for a in extraer(t, c or ctx()).alertas}


@pytest.mark.parametrize(
    ("letras", "esperado"),
    [
        ("ciento veinte", 120),
        ("dos mil veintiseis", 2026),
        ("mil novecientos setenta y cinco", 1975),
        ("cuarenta y cinco millones", 45_000_000),
        ("dos millones trescientos mil quinientos", 2_300_500),
        ("un millon", 1_000_000),
        ("mil millones", 1_000_000_000),
        ("veintiun", 21),
        ("hola", None),
        ("", None),
    ],
)
def test_palabras_a_entero(letras: str, esperado: int | None) -> None:
    assert palabras_a_entero(letras) == esperado


def test_montos() -> None:
    assert monto_ar("45.000.000,50") == Decimal("45000000.50")
    assert monto_ar("1500") == Decimal("1500.00")
    assert monto_en_letras(plano("cuarenta y cinco millones con cincuenta centavos")) == Decimal(
        "45000000.50"
    )
    assert plano("ÁRBOL Ñandú") == "arbol nandu"


def test_minuta_completa() -> None:
    r = extraer(texto(), ctx())
    v = {k: c.valor for k, c in r.campos.items()}
    assert v == {
        "escribano_id": str(TITULAR.escribano_id),
        "tipo_protocolo": "GENERAL",
        "numero_escritura": "120",
        "folio": "345",
        "fecha_acto": "2026-09-14",
        "naturaleza": "Compraventa",
        "categoria": "ESCRITURA_CON_VALOR",
        "base_imponible": "45000000.00",
    }
    # Cada campo explica de dónde salió (XAI).
    assert r.campos["numero_escritura"].regla == "Número en cifras y en letras coinciden."
    evidencia = r.campos["base_imponible"].evidencia
    assert evidencia is not None and "45.000.000,00" in evidencia
    assert r.alertas == []
    assert Decimal("0") < r.confianza() <= Decimal("1")


def test_alertas_de_inconsistencia() -> None:
    assert "NUMERO_LETRAS_DISTINTO" in codigos(texto(numero="CIENTO VEINTIUNO (120)"))
    distinto = texto(precio="PESOS CUARENTA MILLONES ($ 45.000.000,00)")
    assert "MONTO_LETRAS_DISTINTO" in codigos(distinto)
    assert extraer(distinto, ctx()).campos["base_imponible"].confianza < Decimal("0.5")
    fuera = texto(fecha="a los catorce días del mes de agosto del año dos mil veintiséis")
    assert "FECHA_FUERA_DE_PERIODO" in codigos(fuera)
    futura = texto(fecha="14 de diciembre de 2026")
    assert "FECHA_FUTURA" in codigos(futura)
    assert "MONEDA_EXTRANJERA" in codigos(texto(precio="U$S 30.000 (dólares treinta mil)"))
    menor = texto(extra="Comparece además un menor de edad.")
    assert "MENOR_SIN_REPRESENTACION" in codigos(menor)
    con_padres = texto(extra="Comparece un menor de edad representado por sus padres.")
    assert "MENOR_SIN_REPRESENTACION" not in codigos(con_padres)
    assert "CUIT_INVALIDO" in codigos(texto(extra="CUIT 20-12345678-5."))
    assert "CUIT_INVALIDO" not in codigos(texto(extra="CUIT 20-12345678-6."))
    otro_registro = texto(autorizante="María Albarracín, titular del Registro Notarial número 7")
    assert "REGISTRO_DISTINTO" in codigos(otro_registro)
    ya = ctx(declarados=frozenset({("GENERAL", 120)}))
    assert "NUMERO_YA_DECLARADO" in codigos(texto(), ya)


def test_poder_sin_base_imponible() -> None:
    v = valores(texto(naturaleza="PODER ESPECIAL", precio="sin monto"))
    assert v["naturaleza"] == "Poder especial"
    assert v["categoria"] == "ACTA_O_PODER"
    assert v["base_imponible"] == "0.00"


def test_compraventa_sin_monto_avisa() -> None:
    t = texto(precio="lo convenido")
    assert "MONTO_NO_ENCONTRADO" in codigos(t)
    assert valores(t)["categoria"] == "OTRO_ACTO"


def test_equipo_del_registro() -> None:
    """Titular, adscripto y a cargo: el cargo con que se presenta el autorizante desempata."""
    equipo = ctx(TITULAR, ADSCRIPTO, A_CARGO)
    sin_nombre = "ante mí, el Escribano {} del Registro Notarial número 12"
    for cargo, esperado in (("adscripto al", ADSCRIPTO), ("a cargo del", A_CARGO)):
        t = texto(autorizante=sin_nombre.format(cargo).replace(" del Registro", " Registro", 1))
        assert valores(t, equipo)["escribano_id"] == str(esperado.escribano_id), cargo
    # Nombrado por matrícula pero presentado con otro cargo: se avisa.
    t = texto(autorizante="Pedro Quiroga, Escribano titular del Registro número 12, matrícula 789")
    r = extraer(t, equipo)
    assert r.campos["escribano_id"].valor == str(ADSCRIPTO.escribano_id)
    assert "CARGO_DISTINTO" in {a.codigo for a in r.alertas}
    # Sin nombre ni cargo, con varios en el equipo: lo elige la persona.
    anonimo = texto(autorizante="ante mí, el Escribano autorizante")
    assert valores(anonimo, equipo)["escribano_id"] is None
    assert "ESCRIBANO_NO_IDENTIFICADO" in codigos(anonimo, equipo)


def test_texto_escaso() -> None:
    r = extraer("Escritura", ctx())
    assert "TEXTO_ESCASO" in {a.codigo for a in r.alertas}
    assert r.campos["numero_escritura"].valor is None


# --------------------------------------------------------------------------- DNI


def test_pdf417_formato_tarjeta() -> None:
    d = dni.parsear_pdf417(
        "00512345678@SINTETICO DE LA PRUEBA@JUAN CARLOS@M@12345678@B@15/03/1975@10/06/2020@200"
    )
    assert d is not None
    assert (d.numero, d.apellido, d.nombre, d.sexo) == (
        "12345678",
        "SINTETICO DE LA PRUEBA",
        "JUAN CARLOS",
        "M",
    )
    assert d.fecha_nacimiento == date(1975, 3, 15)
    r = dni.a_resultado(d, ya_en_padron=False)
    assert r.campos["apellido"].valor == "Sintetico de la Prueba"
    assert r.campos["cuit"].valor == "20123456786"
    assert r.campos["cuit"].confianza == Decimal("0.50")


def test_pdf417_formato_anterior() -> None:
    d = dni.parsear_pdf417(
        "@12345678    @A@1@SINTETICA@ANA@ARGENTINA@01/02/1980@F@01/01/2012@00012345678@7000 @"
    )
    assert d is not None
    assert (d.numero, d.apellido, d.sexo, d.fecha_nacimiento) == (
        "12345678",
        "SINTETICA",
        "F",
        date(1980, 2, 1),
    )


@pytest.mark.parametrize(
    "contenido",
    [
        "",
        "texto cualquiera",
        "00512345678@APELLIDO@NOMBRE@M@ABC@A@15/03/1975@10/06/2020@200",
        "00512345678@APELLIDO@NOMBRE@M@12345678@A@31/02/1975@10/06/2020@200",
    ],
)
def test_pdf417_invalido(contenido: str) -> None:
    assert dni.parsear_pdf417(contenido) is None


def test_digito_mrz_referencia_icao() -> None:
    # Ejemplo del documento OACI 9303.
    assert dni.digito_mrz("L898902C3") == 6
    assert dni.digito_mrz("740812") == 2


def test_mrz() -> None:
    doc = "12345678<"
    nac = "750315"
    l1 = f"IDARG{doc}{dni.digito_mrz(doc)}".ljust(30, "<")
    l2 = f"{nac}{dni.digito_mrz(nac)}M3001019ARG".ljust(30, "<")
    l3 = "SINTETICO<<JUAN<CARLOS".ljust(30, "<")
    d = dni.parsear_mrz(["ruido", l1, l2, l3], date(2026, 10, 23))
    assert d is not None
    assert (d.numero, d.apellido, d.nombre, d.fecha_nacimiento) == (
        "12345678",
        "SINTETICO",
        "JUAN CARLOS",
        date(1975, 3, 15),
    )
    # Un dígito verificador alterado invalida la lectura.
    malo = l1[:14] + str((dni.digito_mrz(doc) + 1) % 10) + l1[15:]
    assert dni.parsear_mrz([malo, l2, l3], date(2026, 10, 23)) is None


def test_cuil_sugerido() -> None:
    assert dni.cuil_sugerido("12345678", "M") == "20123456786"
    assert dni.cuil_sugerido("12345678", "X") is None
    cuil = dni.cuil_sugerido("12345678", "F")
    assert cuil is not None and cuil[:2] in ("27", "23")


def test_tolera_ruido_de_ocr() -> None:
    """Sin el idioma español instalado, Tesseract cambia letras con tilde: una letra distinta en
    palabras largas se tolera; en palabras cortas no (evita falsos positivos)."""
    assert palabras_a_entero("dos mil veintisxis") == 2026
    assert palabras_a_entero("cuarenta y cinco miliones") == 45_000_000
    assert palabras_a_entero("mal") is None  # no se confunde con "mil"
    ruidoso = (
        "ESCRITURA NXMERO CIENTO VEINTE (120). FOLIO 345. COMPRAVENTA. En San Juan, a los "
        "catorce dXas del mes de septiembre del ao dos mil veintisXis, ante mX, matr&cula 456, "
        "por el precio de PESOS CUARENTA Y CINCO MILLONES ($ 45.000.000,00)."
    )
    v = valores(ruidoso)
    assert v["numero_escritura"] == "120"
    assert v["fecha_acto"] == "2026-09-14"
    assert v["escribano_id"] == str(TITULAR.escribano_id)
    assert v["base_imponible"] == "45000000.00"
