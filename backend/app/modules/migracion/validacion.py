"""Validación del lote: normaliza cada fila y registra observaciones (sin base de datos).

Reglas de calidad de la matriz de homologación (módulo 11 §3): CUIT por Módulo 11, unicidad de
CUIT, número de registro y códigos del origen (CUIT, documento, matrícula, fecha de juramento,
departamento del registro y fecha desde del cargo pueden faltar: se cargan vacíos, «a completar»;
si vienen, se validan), un único titular vigente
por registro, un único cargo vigente por escribano (por su código del origen), licencias sin
solapamiento, estados homologados, fechas y períodos válidos e importes exactos. Una fila con
observación BLOQUEANTE no se carga, ni tampoco las que dependen de ella.

La matrícula NO es única (decisión de la Caja): el Colegio reasigna el número de un escribano
retirado a uno nuevo. Es un dato informativo; identifica el CUIT.

Las observaciones no llevan datos personales: identifican la fila y el código del origen.
"""

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.common.cuit import InvalidCuitError, normalize_cuit
from app.common.dates import today_local
from app.modules.migracion import valores
from app.modules.migracion.catalog import Entidad, EstadoBoletaHistorica, Severidad
from app.modules.migracion.formato import CIRCUNSCRIPCION_POR_DEFECTO, Fila, Lote
from app.modules.migracion.homologacion import Homologacion
from app.modules.migracion.valores import ValorInvalidoError
from app.modules.padron.catalog import (
    DEPARTAMENTOS_SAN_JUAN,
    ESTADOS_DEFINITIVOS,
    Cargo,
    EstadoMatricula,
    EstadoRegistro,
    TipoDocumento,
)

CERO = Decimal("0.00")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True)
class Observacion:
    entidad: Entidad
    fila: int
    codigo_legado: str
    codigo: str
    severidad: Severidad
    mensaje: str


@dataclass(frozen=True)
class RegistroN:
    codigo: str
    numero: int
    circunscripcion: str
    departamento: str | None  # None: «a completar»
    domicilio: str
    estado: str
    nombre_fantasia: str | None
    fecha_creacion: date | None


@dataclass(frozen=True)
class EscribanoN:
    codigo: str
    # None: el origen no lo tiene; se carga vacío («a completar»).
    cuit: str | None
    tipo_documento: str
    numero_documento: str | None
    apellido: str
    nombre: str
    fecha_nacimiento: date | None
    email: str | None
    matricula: int | None
    fecha_matriculacion: date | None
    estado: str
    # Primera escritura: completa (fecha, número y registro) o toda en None.
    primera_escritura_fecha: date | None = None
    primera_escritura_numero: str | None = None
    primera_escritura_registro: int | None = None
    primera_escritura_folio: str | None = None


@dataclass(frozen=True)
class LicenciaN:
    codigo: str
    escribano: str  # codigo_legado del escribano
    desde: date
    hasta: date | None
    motivo: str


@dataclass(frozen=True)
class CargoN:
    codigo: str
    escribano: str  # codigo_legado del escribano
    numero_registro: int
    cargo: str
    desde: date | None  # None: «a completar» (cuenta desde antes de todo lo migrado)
    hasta: date | None


@dataclass(frozen=True)
class BoletaN:
    codigo: str
    # None: el origen no tiene el registro («a completar»): va con `escribano_origen`.
    numero_registro: int | None
    periodo: str
    numero_boleta: str | None
    emision: date
    vencimiento: date
    importe: Decimal
    estado: str
    escribano_origen: str | None = None


@dataclass(frozen=True)
class PagoN:
    codigo: str
    boleta: str
    fecha: date
    importe: Decimal
    medio: str | None


@dataclass(frozen=True)
class CreditoN:
    codigo: str
    numero_registro: int
    fecha: date
    periodo: str | None
    importe: Decimal  # en positivo: a favor del escribano
    concepto: str | None


@dataclass(frozen=True)
class Existentes:
    """Lo que ya está en la Suite: lo migrado no puede chocar con eso."""

    cuits: frozenset[str] = frozenset()
    registros: frozenset[int] = frozenset()


@dataclass
class Staging:
    registros: list[RegistroN] = field(default_factory=list)
    escribanos: list[EscribanoN] = field(default_factory=list)
    cargos: list[CargoN] = field(default_factory=list)
    licencias: list[LicenciaN] = field(default_factory=list)
    boletas: list[BoletaN] = field(default_factory=list)
    pagos: list[PagoN] = field(default_factory=list)
    creditos: list[CreditoN] = field(default_factory=list)
    observaciones: list[Observacion] = field(default_factory=list)
    # Por entidad: filas leídas, rechazadas e importe legible de cada grupo (cuadratura).
    leidas: Counter[str] = field(default_factory=Counter)
    rechazadas: Counter[str] = field(default_factory=Counter)
    importe_leido: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: CERO))
    importe_rechazado: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: CERO))
    importe_ilegible: Counter[str] = field(default_factory=Counter)
    # Día de la corrida: un pago o crédito con fecha posterior se advierte (no se carga distinto).
    fecha_corrida: date = field(default_factory=today_local)

    def bloqueantes(self) -> int:
        return sum(1 for o in self.observaciones if o.severidad is Severidad.BLOQUEANTE)


def _clave(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


_DEPARTAMENTOS = {_clave(d): d for d in DEPARTAMENTOS_SAN_JUAN}


class _Fila:
    """Valida los campos de una fila y junta sus observaciones."""

    def __init__(self, st: Staging, entidad: Entidad, fila: Fila) -> None:
        self.st, self.entidad, self.fila = st, entidad, fila
        self.bloqueada = False
        if not fila.codigo:
            # Sin código no hay trazabilidad origen → Suite (mapeo y cuadratura).
            self.observar("DATO_FALTANTE", "Falta «codigo_legado».")
        elif len(fila.codigo) > 100:
            self.observar("VALOR_INVALIDO", "«codigo_legado» supera los 100 caracteres.")

    def observar(
        self, codigo: str, mensaje: str, severidad: Severidad = Severidad.BLOQUEANTE
    ) -> None:
        self.st.observaciones.append(
            Observacion(
                self.entidad, self.fila.numero, self.fila.codigo, codigo, severidad, mensaje
            )
        )
        if severidad is Severidad.BLOQUEANTE:
            self.bloqueada = True

    def campo(
        self, nombre: str, conversor: Callable[[str], Any], *, obligatorio: bool = True
    ) -> Any:
        crudo = self.fila.datos.get(nombre, "").strip()
        if not crudo:
            if obligatorio:
                self.observar("DATO_FALTANTE", f"Falta «{nombre}».")
            return None
        try:
            return conversor(crudo)
        except ValorInvalidoError as exc:
            self.observar("VALOR_INVALIDO", f"«{nombre}»: {exc}.")
            return None

    def homologar(self, hom: Homologacion, tabla: str, nombre: str) -> str | None:
        crudo = self.fila.datos.get(nombre, "").strip()
        if not crudo:
            self.observar("DATO_FALTANTE", f"Falta «{nombre}».")
            return None
        traducido = hom.traducir(tabla, crudo)
        if traducido is None:
            self.observar(
                "SIN_HOMOLOGACION",
                f"«{nombre}» = «{crudo}» no figura en la tabla de homologación ({tabla}).",
            )
        return traducido


def _duplicados(filas: list[Fila], clave: Callable[[Fila], object]) -> set[int]:
    """Números de fila cuyo valor de `clave` se repite (todas las repetidas, no solo la 2.ª)."""
    grupos: dict[object, list[int]] = defaultdict(list)
    for f in filas:
        valor = clave(f)
        if valor not in (None, ""):
            grupos[valor].append(f.numero)
    return {n for numeros in grupos.values() if len(numeros) > 1 for n in numeros}


def _texto(maximo: int) -> Callable[[str], str]:
    return lambda v: valores.texto(v, maximo)


def _fecha_futura(f: "_Fila", fecha: date | None, que: str) -> None:
    if fecha is not None and fecha > f.st.fecha_corrida:
        f.observar(
            "FECHA_POSTERIOR_A_LA_CORRIDA",
            f"Fecha del {que} posterior al día de la corrida: verificar.",
            Severidad.ADVERTENCIA,
        )


def _cerrar(st: Staging, entidad: Entidad, f: _Fila, importe: Decimal | None = None) -> bool:
    st.leidas[entidad.value] += 1
    if importe is not None:
        st.importe_leido[entidad.value] += importe
    if f.bloqueada:
        st.rechazadas[entidad.value] += 1
        if importe is not None:
            st.importe_rechazado[entidad.value] += importe
    return not f.bloqueada


# --------------------------------------------------------------------------- registros


def _registros(lote: Lote, hom: Homologacion, existentes: Existentes, st: Staging) -> None:
    filas = lote.filas[Entidad.REGISTROS]
    codigos = _duplicados(filas, lambda f: f.codigo)
    numeros = _duplicados(filas, lambda f: f.datos.get("numero_registro", "").strip())
    for fila in filas:
        f = _Fila(st, Entidad.REGISTROS, fila)
        if fila.numero in codigos:
            f.observar("CODIGO_DUPLICADO", "El código del origen se repite en el archivo.")
        numero = f.campo("numero_registro", valores.entero)
        if fila.numero in numeros:
            f.observar("REGISTRO_DUPLICADO", "El número de registro se repite en el archivo.")
        elif numero is not None and numero in existentes.registros:
            f.observar("REGISTRO_EXISTENTE", "El número de registro ya existe en la Suite.")
        if numero == 0:
            f.observar("VALOR_INVALIDO", "«numero_registro» tiene que ser mayor que cero.")
        # La Caja tiene una sola circunscripción: vacía = la de San Juan.
        circ = (
            f.campo("circunscripcion", _texto(100), obligatorio=False)
            or CIRCUNSCRIPCION_POR_DEFECTO
        )
        depto_crudo = f.campo("departamento", _texto(100), obligatorio=False)
        departamento = _DEPARTAMENTOS.get(_clave(depto_crudo)) if depto_crudo else None
        if depto_crudo and departamento is None:
            f.observar("DEPARTAMENTO_DESCONOCIDO", "El departamento no es uno de San Juan.")
        domicilio = f.campo("domicilio_legal", _texto(500))
        estado = f.homologar(hom, "estado_registro", "estado")
        fantasia = f.campo("nombre_fantasia", _texto(150), obligatorio=False)
        creacion = f.campo("fecha_creacion", valores.fecha, obligatorio=False)
        if _cerrar(st, Entidad.REGISTROS, f):
            st.registros.append(
                RegistroN(
                    fila.codigo,
                    numero,
                    circ,
                    departamento,
                    domicilio,
                    estado or "",
                    fantasia,
                    creacion,
                )
            )


# --------------------------------------------------------------------------- escribanos


def _cuit(valor: str) -> str:
    try:
        return normalize_cuit(valor)
    except InvalidCuitError as exc:
        raise ValorInvalidoError(str(exc).rstrip(".").lower()) from exc


def _escribanos(lote: Lote, hom: Homologacion, existentes: Existentes, st: Staging) -> None:
    filas = lote.filas[Entidad.ESCRIBANOS]
    codigos = _duplicados(filas, lambda f: f.codigo)

    def cuit_de(f: Fila) -> str | None:
        try:
            return normalize_cuit(f.datos.get("cuit", ""))
        except InvalidCuitError:
            return None

    cuits = _duplicados(filas, cuit_de)
    for fila in filas:
        f = _Fila(st, Entidad.ESCRIBANOS, fila)
        if fila.numero in codigos:
            f.observar("CODIGO_DUPLICADO", "El código del origen se repite en el archivo.")
        cuit = f.campo("cuit", _cuit, obligatorio=False)
        if fila.numero in cuits:
            f.observar("CUIT_DUPLICADO", "El CUIT se repite en el archivo.")
        elif cuit is not None and cuit in existentes.cuits:
            f.observar("CUIT_EXISTENTE", "El CUIT ya existe en la Suite.")
        tipo = (fila.datos.get("tipo_documento") or "DNI").strip().upper()
        if tipo not in {t.value for t in TipoDocumento}:
            f.observar("VALOR_INVALIDO", "«tipo_documento» no es DNI, LC, LE ni PASAPORTE.")
        documento = f.campo("numero_documento", _texto(15), obligatorio=False)
        if tipo == "DNI" and cuit and documento and documento.zfill(8) != cuit[2:10]:
            f.observar(
                "DNI_DISTINTO_DEL_CUIT",
                "El DNI no coincide con el del CUIT: verificar.",
                Severidad.ADVERTENCIA,
            )
        apellido = f.campo("apellido", _texto(100))
        nombre = f.campo("nombre", _texto(100))
        nacimiento = f.campo("fecha_nacimiento", valores.fecha, obligatorio=False)
        email = (fila.datos.get("email") or "").strip().lower() or None
        if email and not _EMAIL.fullmatch(email):
            f.observar(
                "EMAIL_INVALIDO", "El correo no es válido: no se migra.", Severidad.ADVERTENCIA
            )
            email = None
        # Informativa: puede repetirse (matrícula reasignada) y no choca con la Suite.
        matricula = f.campo("matricula", valores.entero, obligatorio=False)
        if matricula == 0:
            f.observar("VALOR_INVALIDO", "«matricula» tiene que ser mayor que cero.")
        matriculacion = f.campo("fecha_matriculacion", valores.fecha, obligatorio=False)
        estado = f.homologar(hom, "estado_escribano", "estado")
        primera = _primera_escritura(f, matriculacion)
        if _cerrar(st, Entidad.ESCRIBANOS, f):
            st.escribanos.append(
                EscribanoN(
                    fila.codigo,
                    cuit,
                    tipo,
                    documento,
                    apellido,
                    nombre,
                    nacimiento,
                    email,
                    matricula,
                    matriculacion,
                    estado or "",
                    *primera,
                )
            )


_PRIMERA = (
    "primera_escritura_fecha",
    "primera_escritura_numero",
    "primera_escritura_registro",
    "primera_escritura_folio",
)
_SIN_PRIMERA: tuple[None, None, None, None] = (None, None, None, None)


def _primera_escritura(
    f: _Fila, juramento: date | None
) -> tuple[date | None, str | None, int | None, str | None]:
    """Primera escritura de la fila. Un dato inválido o incompleto no rechaza al escribano:
    se advierte y la primera escritura queda «a completar» (la carga después la Caja)."""
    crudos = {c: f.fila.datos.get(c, "").strip() for c in _PRIMERA}
    if not any(crudos.values()):
        return _SIN_PRIMERA

    def no_migra(motivo: str) -> tuple[None, None, None, None]:
        f.observar(
            "PRIMERA_ESCRITURA_NO_MIGRADA",
            f"Primera escritura no migrada ({motivo}): queda a completar.",
            Severidad.ADVERTENCIA,
        )
        return _SIN_PRIMERA

    faltan = [c for c in _PRIMERA[:3] if not crudos[c]]
    if faltan:
        return no_migra(f"falta {', '.join(faltan)}")
    try:
        fecha = valores.fecha(crudos["primera_escritura_fecha"])
        registro = valores.entero(crudos["primera_escritura_registro"])
        numero = valores.texto(crudos["primera_escritura_numero"], 20)
        folio_crudo = crudos["primera_escritura_folio"]
        folio = valores.texto(folio_crudo, 20) if folio_crudo else None
    except ValorInvalidoError as exc:
        return no_migra(str(exc))
    if registro <= 0:
        return no_migra("el registro tiene que ser mayor que cero")
    if fecha > f.st.fecha_corrida:
        return no_migra("la fecha es posterior al día de la corrida")
    if juramento is not None and fecha < juramento:
        f.observar(
            "PRIMERA_ESCRITURA_ANTERIOR_AL_JURAMENTO",
            "La primera escritura es anterior a la fecha de juramento: verificar.",
            Severidad.ADVERTENCIA,
        )
    return fecha, numero, registro, folio


# --------------------------------------------------------------------------- cargos


def _cargos(lote: Lote, hom: Homologacion, st: Staging) -> None:
    filas = lote.filas[Entidad.CARGOS]
    codigos = _duplicados(filas, lambda f: f.codigo)
    escribanos = {e.codigo: e for e in st.escribanos}
    registros = {r.numero for r in st.registros}
    candidatos: list[tuple[_Fila, CargoN]] = []
    for fila in filas:
        f = _Fila(st, Entidad.CARGOS, fila)
        if fila.numero in codigos:
            f.observar("CODIGO_DUPLICADO", "El código del origen se repite en el archivo.")
        codigo_escribano = f.campo("escribano", _texto(100))
        numero = f.campo("numero_registro", valores.entero)
        if codigo_escribano is not None and codigo_escribano not in escribanos:
            f.observar(
                "ESCRIBANO_NO_MIGRADO",
                "«escribano» no corresponde a un escribano del lote que se pueda cargar.",
            )
        if numero is not None and numero not in registros:
            f.observar(
                "REGISTRO_NO_MIGRADO",
                "El registro no corresponde a un registro del lote que se pueda cargar.",
            )
        cargo = f.homologar(hom, "cargo", "cargo")
        desde = f.campo("fecha_desde", valores.fecha, obligatorio=False)
        if desde is None and not fila.datos.get("fecha_desde", "").strip():
            f.observar(
                "FECHA_DESDE_A_COMPLETAR",
                "Falta la fecha desde del cargo: queda a completar y el cargo cuenta desde antes "
                "de todo lo migrado.",
                Severidad.ADVERTENCIA,
            )
        hasta = f.campo("fecha_hasta", valores.fecha, obligatorio=False)
        if desde and hasta and hasta < desde:
            f.observar("FECHAS_INVERTIDAS", "«fecha_hasta» es anterior a «fecha_desde».")
        escribano = escribanos.get(codigo_escribano) if codigo_escribano else None
        if (
            escribano is not None
            and hasta is None
            and EstadoMatricula(escribano.estado) in ESTADOS_DEFINITIVOS
        ):
            f.observar(
                "CARGO_VIGENTE_SIN_EJERCICIO",
                "Cargo vigente de un escribano cesante, jubilado o fallecido.",
            )
        if not f.bloqueada:
            candidatos.append(
                (f, CargoN(fila.codigo, codigo_escribano, numero, cargo or "", desde, hasta))
            )
        else:
            _cerrar(st, Entidad.CARGOS, f)

    # Unicidad de vigentes: se observan todas las filas en conflicto (no se elige una).
    vigentes_escribano = Counter(c.escribano for _, c in candidatos if c.hasta is None)
    titulares = Counter(
        c.numero_registro for _, c in candidatos if c.hasta is None and c.cargo == Cargo.TITULAR
    )
    for f, c in candidatos:
        if c.hasta is None and vigentes_escribano[c.escribano] > 1:
            f.observar("CARGOS_VIGENTES_MULTIPLES", "El escribano tiene más de un cargo vigente.")
        if c.hasta is None and c.cargo == Cargo.TITULAR and titulares[c.numero_registro] > 1:
            f.observar("TITULARES_MULTIPLES", "El registro tiene más de un titular vigente.")
        if _cerrar(st, Entidad.CARGOS, f):
            st.cargos.append(c)

    titulares_ok = {
        c.numero_registro for c in st.cargos if c.hasta is None and c.cargo == Cargo.TITULAR
    }
    for r in st.registros:
        if r.estado == EstadoRegistro.ACTIVO and r.numero not in titulares_ok:
            st.observaciones.append(
                Observacion(
                    Entidad.REGISTROS,
                    0,
                    r.codigo,
                    "REGISTRO_ACTIVO_SIN_TITULAR",
                    Severidad.ADVERTENCIA,
                    "Registro activo sin titular vigente.",
                )
            )


# --------------------------------------------------------------------------- licencias


MOTIVO_LICENCIA_MIGRADA = "Migrada del sistema anterior"


def _licencias(lote: Lote, st: Staging) -> None:
    """Licencias de escribanos (archivo opcional). Una licencia de un escribano que no se carga
    cae en cascada; dos licencias del mismo escribano que se superponen se observan las dos."""
    filas = lote.filas[Entidad.LICENCIAS]
    codigos = _duplicados(filas, lambda f: f.codigo)
    escribanos = {e.codigo: e for e in st.escribanos}
    candidatas: list[tuple[_Fila, LicenciaN]] = []
    for fila in filas:
        f = _Fila(st, Entidad.LICENCIAS, fila)
        if fila.numero in codigos:
            f.observar("CODIGO_DUPLICADO", "El código del origen se repite en el archivo.")
        codigo_escribano = f.campo("escribano", _texto(100))
        escribano = escribanos.get(codigo_escribano) if codigo_escribano else None
        if codigo_escribano is not None and escribano is None:
            f.observar(
                "ESCRIBANO_NO_MIGRADO",
                "«escribano» no corresponde a un escribano del lote que se pueda cargar.",
            )
        desde = f.campo("fecha_desde", valores.fecha)
        hasta = f.campo("fecha_hasta", valores.fecha, obligatorio=False)
        if desde and hasta and hasta < desde:
            f.observar("FECHAS_INVERTIDAS", "«fecha_hasta» es anterior a «fecha_desde».")
        motivo = f.campo("motivo", _texto(1000), obligatorio=False) or MOTIVO_LICENCIA_MIGRADA
        if escribano is not None and desde is not None:
            sigue = hasta is None or hasta >= st.fecha_corrida
            if sigue and EstadoMatricula(escribano.estado) in ESTADOS_DEFINITIVOS:
                f.observar(
                    "LICENCIA_VIGENTE_SIN_EJERCICIO",
                    "Licencia vigente de un escribano cesante, jubilado o fallecido: falta la "
                    "fecha de regreso.",
                )
            juramento = escribano.fecha_matriculacion
            if juramento is not None and desde < juramento:
                f.observar(
                    "LICENCIA_ANTERIOR_AL_JURAMENTO",
                    "La licencia empieza antes de la fecha de juramento: verificar.",
                    Severidad.ADVERTENCIA,
                )
        if f.bloqueada:
            _cerrar(st, Entidad.LICENCIAS, f)
        else:
            candidatas.append((f, LicenciaN(fila.codigo, codigo_escribano, desde, hasta, motivo)))

    # Sin solapamiento por escribano: se observan todas las filas en conflicto (no se elige).
    por_escribano: dict[str, list[LicenciaN]] = defaultdict(list)
    for _, lic in candidatas:
        por_escribano[lic.escribano].append(lic)
    for f, lic in candidatas:
        if any(
            otra is not lic
            and otra.desde <= (lic.hasta or date.max)
            and lic.desde <= (otra.hasta or date.max)
            for otra in por_escribano[lic.escribano]
        ):
            f.observar("LICENCIAS_SUPERPUESTAS", "La licencia se superpone con otra del escribano.")
        if _cerrar(st, Entidad.LICENCIAS, f):
            st.licencias.append(lic)


# --------------------------------------------------------------------------- boletas y pagos


def _boletas(lote: Lote, hom: Homologacion, st: Staging) -> None:
    filas = lote.filas[Entidad.BOLETAS]
    codigos = _duplicados(filas, lambda f: f.codigo)
    registros = {r.numero for r in st.registros}
    for fila in filas:
        f = _Fila(st, Entidad.BOLETAS, fila)
        if fila.numero in codigos:
            f.observar("CODIGO_DUPLICADO", "El código del origen se repite en el archivo.")
        escribano_origen = f.campo("escribano_origen", _texto(200), obligatorio=False)
        # Sin registro en el origen, la boleta se carga igual si dice quién pagó: la Caja le
        # asigna el registro después (una sola vez, auditado).
        numero = f.campo("numero_registro", valores.entero, obligatorio=escribano_origen is None)
        if (
            numero is None
            and escribano_origen
            and not fila.datos.get("numero_registro", "").strip()
        ):
            f.observar(
                "REGISTRO_A_COMPLETAR",
                "Sin registro en el origen: se carga con el nombre de quien pagó y el registro "
                "queda a completar.",
                Severidad.ADVERTENCIA,
            )
        if numero is not None and numero not in registros:
            f.observar(
                "REGISTRO_NO_MIGRADO",
                "El registro no corresponde a un registro del lote que se pueda cargar.",
            )
        periodo = f.campo("periodo", valores.periodo)
        numero_boleta = (fila.datos.get("numero_boleta") or "").strip() or None
        emision = f.campo("fecha_emision", valores.fecha)
        vencimiento = f.campo("fecha_vencimiento", valores.fecha)
        if emision and vencimiento and vencimiento < emision:
            f.observar(
                "VENCIMIENTO_ANTERIOR",
                "El vencimiento es anterior a la emisión: verificar.",
                Severidad.ADVERTENCIA,
            )
        importe = f.campo("importe", valores.importe)
        if importe is None and fila.datos.get("importe", "").strip():
            st.importe_ilegible[Entidad.BOLETAS.value] += 1
        if importe is not None and importe < 0:
            f.observar("IMPORTE_NEGATIVO", "El importe de la boleta es negativo.")
        estado = f.homologar(hom, "estado_boleta", "estado")
        if _cerrar(st, Entidad.BOLETAS, f, importe):
            st.boletas.append(
                BoletaN(
                    fila.codigo,
                    numero,
                    periodo,
                    numero_boleta,
                    emision,
                    vencimiento,
                    importe,
                    estado or "",
                    escribano_origen,
                )
            )


def _pagos(lote: Lote, st: Staging) -> None:
    filas = lote.filas[Entidad.PAGOS]
    codigos = _duplicados(filas, lambda f: f.codigo)
    boletas = {b.codigo: b for b in st.boletas}
    pagado: dict[str, Decimal] = defaultdict(lambda: CERO)
    filas_de: dict[str, list[_Fila]] = defaultdict(list)
    for fila in filas:
        f = _Fila(st, Entidad.PAGOS, fila)
        if fila.numero in codigos:
            f.observar("CODIGO_DUPLICADO", "El código del origen se repite en el archivo.")
        boleta_codigo = f.campo("boleta", _texto(100))
        boleta = boletas.get(boleta_codigo) if boleta_codigo else None
        if boleta_codigo and boleta is None:
            f.observar("BOLETA_NO_MIGRADA", "La boleta no se puede cargar o no existe en el lote.")
        fecha = f.campo("fecha_pago", valores.fecha)
        _fecha_futura(f, fecha, "pago")
        importe = f.campo("importe", valores.importe)
        if importe is None and fila.datos.get("importe", "").strip():
            st.importe_ilegible[Entidad.PAGOS.value] += 1
        if importe is not None and importe <= 0:
            f.observar("IMPORTE_NO_POSITIVO", "El importe del pago tiene que ser mayor que cero.")
        if boleta is not None and boleta.estado == EstadoBoletaHistorica.ANULADA:
            f.observar(
                "PAGO_DE_BOLETA_ANULADA",
                "Pago de una boleta anulada: verificar.",
                Severidad.ADVERTENCIA,
            )
        medio = f.campo("medio", _texto(50), obligatorio=False)
        if _cerrar(st, Entidad.PAGOS, f, importe):
            st.pagos.append(PagoN(fila.codigo, boleta_codigo, fecha, importe, medio))
            pagado[boleta_codigo] += importe
            filas_de[boleta_codigo].append(f)

    # Coherencia entre el estado de la boleta y lo pagado (se informa, no se corrige).
    for b in st.boletas:
        total = pagado.get(b.codigo, CERO)
        if total > b.importe:
            mensaje, codigo = "Lo pagado supera el importe de la boleta.", "PAGO_EXCEDENTE"
        elif b.estado == EstadoBoletaHistorica.PAGADA and total < b.importe:
            mensaje, codigo = (
                "Boleta pagada con pagos por menos de su importe.",
                "PAGADA_INCOMPLETA",
            )
        elif b.estado == EstadoBoletaHistorica.IMPAGA and total >= b.importe and total > 0:
            mensaje, codigo = "Boleta impaga con pagos por su importe completo.", "IMPAGA_CANCELADA"
        else:
            continue
        st.observaciones.append(
            Observacion(Entidad.BOLETAS, 0, b.codigo, codigo, Severidad.ADVERTENCIA, mensaje)
        )


# --------------------------------------------------------------------------- créditos


def _creditos(lote: Lote, st: Staging) -> None:
    """Créditos a favor del escribano (importes negativos del libro del origen, en positivo).

    TODO(negocio): decidir si el saldo a favor del sistema anterior compensa deuda
    (préstamos, garantes, boletas nuevas).
    """
    filas = lote.filas[Entidad.CREDITOS]
    codigos = _duplicados(filas, lambda f: f.codigo)
    registros = {r.numero for r in st.registros}
    for fila in filas:
        f = _Fila(st, Entidad.CREDITOS, fila)
        if fila.numero in codigos:
            f.observar("CODIGO_DUPLICADO", "El código del origen se repite en el archivo.")
        numero = f.campo("numero_registro", valores.entero)
        if numero is not None and numero not in registros:
            f.observar(
                "REGISTRO_NO_MIGRADO",
                "El registro no corresponde a un registro del lote que se pueda cargar.",
            )
        fecha = f.campo("fecha", valores.fecha)
        _fecha_futura(f, fecha, "crédito")
        periodo = f.campo("periodo", valores.periodo, obligatorio=False)
        importe = f.campo("importe", valores.importe)
        if importe is None and fila.datos.get("importe", "").strip():
            st.importe_ilegible[Entidad.CREDITOS.value] += 1
        if importe is not None and importe <= 0:
            f.observar(
                "IMPORTE_NO_POSITIVO",
                "El importe del crédito va en positivo y tiene que ser mayor que cero.",
            )
        concepto = f.campo("concepto", _texto(100), obligatorio=False)
        if _cerrar(st, Entidad.CREDITOS, f, importe):
            st.creditos.append(CreditoN(fila.codigo, numero, fecha, periodo, importe, concepto))


def validar(
    lote: Lote, hom: Homologacion, existentes: Existentes, fecha_corrida: date | None = None
) -> Staging:
    st = Staging(fecha_corrida=fecha_corrida or today_local())
    _registros(lote, hom, existentes, st)
    _escribanos(lote, hom, existentes, st)
    _cargos(lote, hom, st)
    _licencias(lote, st)
    _boletas(lote, hom, st)
    _pagos(lote, st)
    _creditos(lote, st)
    return st
