"""Lectura asistida del DNI argentino: código PDF417 del frente o zona MRZ del dorso.

El PDF417 trae los datos en texto plano separado por "@" y con corrección de errores propia: si
se decodifica y los campos validan, la lectura es confiable. La MRZ (dorso, formato TD1 de
OACI 9303) se lee por OCR y se valida con sus dígitos verificadores.

Lo que no está en el DNI no se inventa: el CUIL se propone a partir del número y el sexo con el
algoritmo público de AFIP, como sugerencia de baja confianza que hay que verificar con la
constancia. La comparación facial 1:1 no se implementa (ver README: TODO(negocio)).
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.common.cuit import check_digit
from app.modules.ia.catalog import (
    MOTOR_DNI_MRZ,
    MOTOR_DNI_PDF417,
    NivelAlerta,
)
from app.modules.ia.resultado import Alerta, Campo, Resultado

CONFIANZA_PDF417 = Decimal("0.98")
CONFIANZA_MRZ = Decimal("0.90")
CONFIANZA_CUIL = Decimal("0.50")


@dataclass(frozen=True)
class DatosDni:
    numero: str
    apellido: str
    nombre: str
    sexo: str | None
    fecha_nacimiento: date | None
    ejemplar: str | None
    fecha_emision: date | None
    motor: str
    evidencia: str


def _fecha_ddmmaaaa(valor: str) -> date | None:
    m = re.fullmatch(r"\s*([0-9]{2})/([0-9]{2})/([0-9]{4})\s*", valor)
    if m is None:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _numero_dni(valor: str) -> str | None:
    digitos = valor.strip()
    return digitos if re.fullmatch(r"[0-9]{7,8}", digitos) else None


def _sexo(valor: str) -> str | None:
    v = valor.strip().upper()
    return v if v in ("M", "F", "X") else None


def _nombre(valor: str) -> str:
    return " ".join(valor.split())


def _evidencia_pdf417(numero: str, apellido: str) -> str:
    # Sin volcar el contenido completo del código: alcanza para identificar la lectura.
    return f"Código PDF417 del frente: {apellido} · DNI {numero}"


def parsear_pdf417(texto: str) -> DatosDni | None:
    """Formato de la tarjeta (2012 en adelante) y el del primer DNI tarjeta (comienza con "@")."""
    campos = texto.split("@")
    if len(campos) >= 8 and re.fullmatch(r"[0-9]{8,11}", campos[0].strip()):
        # trámite@apellido@nombre@sexo@número@ejemplar@nacimiento@emisión@…
        numero = _numero_dni(campos[4])
        nacimiento = _fecha_ddmmaaaa(campos[6])
        if numero is None or nacimiento is None or not campos[1].strip():
            return None
        return DatosDni(
            numero=numero,
            apellido=_nombre(campos[1]),
            nombre=_nombre(campos[2]),
            sexo=_sexo(campos[3]),
            fecha_nacimiento=nacimiento,
            ejemplar=campos[5].strip() or None,
            fecha_emision=_fecha_ddmmaaaa(campos[7]),
            motor=MOTOR_DNI_PDF417,
            evidencia=_evidencia_pdf417(numero, _nombre(campos[1])),
        )
    if len(campos) >= 10 and campos[0] == "":
        # @número@ejemplar@?@apellido@nombre@nacionalidad@nacimiento@sexo@emisión@…
        numero = _numero_dni(campos[1])
        nacimiento = _fecha_ddmmaaaa(campos[7])
        if numero is None or nacimiento is None or not campos[4].strip():
            return None
        return DatosDni(
            numero=numero,
            apellido=_nombre(campos[4]),
            nombre=_nombre(campos[5]),
            sexo=_sexo(campos[8]),
            fecha_nacimiento=nacimiento,
            ejemplar=campos[2].strip() or None,
            fecha_emision=_fecha_ddmmaaaa(campos[9]),
            motor=MOTOR_DNI_PDF417,
            evidencia=_evidencia_pdf417(numero, _nombre(campos[4])),
        )
    return None


# --------------------------------------------------------------------------- MRZ (dorso)

_PESOS_MRZ = (7, 3, 1)


def _valor_mrz(c: str) -> int:
    if c.isdigit():
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - 55
    return 0  # "<"


def digito_mrz(datos: str) -> int:
    return sum(_valor_mrz(c) * _PESOS_MRZ[i % 3] for i, c in enumerate(datos)) % 10


def _fecha_mrz(aammdd: str, hoy: date) -> date | None:
    if not re.fullmatch(r"[0-9]{6}", aammdd):
        return None
    aa, mm, dd = int(aammdd[:2]), int(aammdd[2:4]), int(aammdd[4:])
    # Fecha de nacimiento: si el año de dos cifras supera el actual, es del siglo anterior.
    anio = 2000 + aa if 2000 + aa <= hoy.year else 1900 + aa
    try:
        return date(anio, mm, dd)
    except ValueError:
        return None


def parsear_mrz(lineas: list[str], hoy: date) -> DatosDni | None:
    """TD1: tres líneas de 30 caracteres. Valida los dígitos del documento y del nacimiento."""
    limpias = [re.sub(r"\s", "", ln.upper()) for ln in lineas]
    candidatas = [ln for ln in limpias if re.fullmatch(r"[A-Z0-9<]{30}", ln)]
    for i in range(len(candidatas) - 2):
        l1, l2, l3 = candidatas[i : i + 3]
        if not (l1.startswith("ID") and l1[2:5] == "ARG"):
            continue
        documento, chk_doc = l1[5:14], l1[14]
        nacimiento, chk_nac = l2[0:6], l2[6]
        if not chk_doc.isdigit() or digito_mrz(documento) != int(chk_doc):
            continue
        if not chk_nac.isdigit() or digito_mrz(nacimiento) != int(chk_nac):
            continue
        numero = _numero_dni(documento.replace("<", ""))
        fecha = _fecha_mrz(nacimiento, hoy)
        apellido, _, nombre = l3.partition("<<")
        if numero is None or fecha is None or not apellido.strip("<"):
            continue
        return DatosDni(
            numero=numero,
            apellido=" ".join(apellido.split("<")).strip(),
            nombre=" ".join(nombre.split("<")).strip(),
            sexo=_sexo(l2[7]),
            fecha_nacimiento=fecha,
            ejemplar=None,
            fecha_emision=None,
            motor=MOTOR_DNI_MRZ,
            evidencia=f"Zona MRZ del dorso: {l1}",
        )
    return None


# --------------------------------------------------------------------------- sugerencia


def cuil_sugerido(numero: str, sexo: str | None) -> str | None:
    """Algoritmo público de AFIP: 20 (masculino) o 27 (femenino) + DNI + dígito Módulo 11; si el
    dígito da 10, el prefijo pasa a 23 con dígito 9 (masculino) o 4 (femenino)."""
    if sexo not in ("M", "F"):
        return None
    dni = numero.zfill(8)
    prefijo = "20" if sexo == "M" else "27"
    digito = check_digit(prefijo + dni)
    if digito is None:
        return f"23{dni}{9 if sexo == 'M' else 4}"
    return f"{prefijo}{dni}{digito}"


def _capitalizar(valor: str) -> str:
    """ "DE LA FUENTE" → "De la Fuente" (el DNI viene en mayúsculas)."""
    minusculas = {"de", "del", "la", "las", "los", "y", "e"}
    palabras = valor.lower().split()
    return " ".join(
        p if (i > 0 and p in minusculas) else p[:1].upper() + p[1:] for i, p in enumerate(palabras)
    )


def a_resultado(datos: DatosDni, ya_en_padron: bool) -> Resultado:
    confianza = CONFIANZA_PDF417 if datos.motor == MOTOR_DNI_PDF417 else CONFIANZA_MRZ
    origen = "Código PDF417 del frente" if datos.motor == MOTOR_DNI_PDF417 else "Zona MRZ del dorso"
    validado = f"{origen}, validado."
    campos = {
        "numero_documento": Campo(datos.numero, confianza, validado, datos.evidencia),
        "apellido": Campo(_capitalizar(datos.apellido), confianza, validado, datos.evidencia),
        "nombre": Campo(
            _capitalizar(datos.nombre) or None,
            confianza if datos.nombre else Decimal("0"),
            validado,
            datos.evidencia,
        ),
        "fecha_nacimiento": Campo(
            datos.fecha_nacimiento.isoformat() if datos.fecha_nacimiento else None,
            confianza if datos.fecha_nacimiento else Decimal("0"),
            validado,
            datos.evidencia,
        ),
        "cuit": Campo(
            cuil_sugerido(datos.numero, datos.sexo),
            CONFIANZA_CUIL if datos.sexo in ("M", "F") else Decimal("0"),
            "Calculado con el DNI y el sexo (algoritmo de AFIP): verificalo con la constancia de "
            "CUIL/CUIT, puede tener otro prefijo.",
        ),
    }
    alertas: list[Alerta] = []
    if ya_en_padron:
        alertas.append(
            Alerta(
                "DNI_EN_PADRON",
                NivelAlerta.ADVERTENCIA,
                f"Ya hay una persona con el DNI {datos.numero} en el padrón.",
            )
        )
    if campos["cuit"].valor is None:
        alertas.append(
            Alerta(
                "CUIL_NO_SUGERIDO",
                NivelAlerta.AVISO,
                "No se pudo proponer el CUIL (sexo no informado o no binario): cargalo desde la "
                "constancia.",
            )
        )
    if datos.ejemplar:
        alertas.append(
            Alerta(
                "EJEMPLAR",
                NivelAlerta.AVISO,
                f"Ejemplar {datos.ejemplar}"
                + (f", emitido el {datos.fecha_emision:%d/%m/%Y}" if datos.fecha_emision else "")
                + ": verificá que sea el vigente.",
            )
        )
    return Resultado(campos, alertas)
