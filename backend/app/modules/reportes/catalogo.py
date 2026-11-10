"""Catálogo de reportes. Cada consulta etiqueta sus columnas con las `key` declaradas y fija un
orden total (con desempate por id) para que paginar y exportar den exactamente las mismas filas."""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Date, Integer, String, and_, case, cast, func, literal, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.common.audit import AuditSecurityLog, Severity
from app.common.dates import LOCAL_TZ, today_local
from app.modules.ddjj.catalog import CategoriaActo, EstadoBoleta, EstadoDDJJ
from app.modules.ddjj.models import Acto, Boleta, DeclaracionJurada
from app.modules.ia.catalog import EstadoSugerencia, TipoSugerencia
from app.modules.ia.models import Sugerencia
from app.modules.iam.catalog import Perm
from app.modules.iam.models import User
from app.modules.migracion.catalog import EstadoBoletaHistorica
from app.modules.migracion.models import HistoricoBoleta, HistoricoCredito, HistoricoPago
from app.modules.padron.catalog import DEPARTAMENTOS_SAN_JUAN, Cargo, EstadoMatricula
from app.modules.padron.models import (
    Adscripcion,
    Escribano,
    Licencia,
    Persona,
    RegistroNotarial,
)
from app.modules.pagos.catalog import ResultadoConciliacion
from app.modules.pagos.models import Comprobante, Conciliacion
from app.modules.previsional.models import Ejercicio, PuntosAfiliado
from app.modules.reportes.framework import (
    ESCRIBANO_PROPIO,
    Columna,
    Consulta,
    Filtro,
    Filtros,
    Reporte,
    Tipo,
    TipoFiltro,
)

TZ = str(LOCAL_TZ)


def _fecha_local(col: Any) -> ColumnElement[date]:
    """Fecha calendario en San Juan de un timestamp UTC (filtros por día, como en pantalla)."""
    return cast(func.timezone(TZ, col), Date)


def _rango_fechas(stmt: Consulta, col: Any, f: Filtros) -> Consulta:
    if "fecha_desde" in f:
        stmt = stmt.where(_fecha_local(col) >= f["fecha_desde"])
    if "fecha_hasta" in f:
        stmt = stmt.where(_fecha_local(col) <= f["fecha_hasta"])
    return stmt


def _rango_periodos(stmt: Consulta, col: Any, f: Filtros) -> Consulta:
    if "periodo_desde" in f:
        stmt = stmt.where(col >= f["periodo_desde"])
    if "periodo_hasta" in f:
        stmt = stmt.where(col <= f["periodo_hasta"])
    return stmt


PERIODOS = (
    Filtro("periodo_desde", "Período desde", TipoFiltro.PERIODO),
    Filtro("periodo_hasta", "Período hasta", TipoFiltro.PERIODO),
)
FECHAS = (
    Filtro("fecha_desde", "Desde", TipoFiltro.FECHA),
    Filtro("fecha_hasta", "Hasta", TipoFiltro.FECHA),
)

# --------------------------------------------------------------------------- escribanos

# Dato que faltaba en el sistema anterior y la Caja todavía no cargó.
A_COMPLETAR = "A completar"

CARGO_TEXTO = {
    Cargo.TITULAR.value: "Titular",
    Cargo.ADSCRIPTO.value: "Adscripto",
    Cargo.SUPLENTE_INTERINO.value: "A cargo",
}


def _escribanos(f: Filtros) -> Consulta:
    cargo = aliased(Adscripcion)
    registro = aliased(RegistroNotarial)
    stmt = (
        select(
            Escribano.matricula_numero.label("matricula"),
            (Persona.apellido + ", " + Persona.nombre).label("apellido_nombre"),
            Persona.cuit.label("cuit"),
            Escribano.estado_matricula.label("estado"),
            registro.numero_registro.label("registro"),
            cargo.cargo.label("cargo"),
            registro.departamento.label("departamento"),
            Escribano.fecha_matriculacion.label("fecha_matriculacion"),
            Escribano.primera_escritura_fecha.label("primera_escritura"),
            Persona.email.label("email"),
            Persona.telefono.label("telefono"),
        )
        .join(Persona, Persona.id == Escribano.persona_id)
        .outerjoin(cargo, and_(cargo.escribano_id == Escribano.id, cargo.is_current.is_(True)))
        .outerjoin(registro, registro.id == cargo.registro_id)
    )
    if "estado" in f:
        stmt = stmt.where(Escribano.estado_matricula == f["estado"])
    if "departamento" in f:
        stmt = stmt.where(registro.departamento == f["departamento"])
    if "q" in f:
        like = f"%{f['q'].lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Persona.apellido + ", " + Persona.nombre).like(like),
                cast(Escribano.matricula_numero, String) == f["q"],
            )
        )
    return stmt.order_by(Persona.apellido, Persona.nombre, Escribano.id)


ESCRIBANOS = Reporte(
    codigo="ESCRIBANOS",
    construir=_escribanos,
    titulo="Padrón de escribanos",
    descripcion="Matriculados con su estado, cargo vigente y registro.",
    permiso=Perm.ESCRIBANOS_READ,
    sensible=True,
    columnas=(
        Columna("matricula", "Matrícula", Tipo.ENTERO, vacio=A_COMPLETAR),
        Columna("apellido_nombre", "Apellido y nombre"),
        Columna("cuit", "CUIT", Tipo.CUIT, vacio=A_COMPLETAR),
        Columna("estado", "Estado"),
        Columna("registro", "Registro", Tipo.ENTERO),
        Columna("cargo", "Cargo"),
        Columna("departamento", "Departamento", visible=False),
        Columna(
            "fecha_matriculacion",
            "Fecha de juramento",
            Tipo.FECHA,
            visible=False,
            vacio=A_COMPLETAR,
        ),
        Columna(
            "primera_escritura", "Primera escritura", Tipo.FECHA, visible=False, vacio=A_COMPLETAR
        ),
        Columna("email", "Correo", visible=False),
        Columna("telefono", "Teléfono", visible=False),
    ),
    filtros=(
        Filtro("q", "Apellido, nombre o matrícula", TipoFiltro.TEXTO),
        Filtro(
            "estado",
            "Estado de la matrícula",
            TipoFiltro.OPCIONES,
            tuple((e.value, e.value.capitalize()) for e in EstadoMatricula),
        ),
        Filtro(
            "departamento",
            "Departamento",
            TipoFiltro.OPCIONES,
            tuple((d, d) for d in DEPARTAMENTOS_SAN_JUAN),
        ),
    ),
)

# --------------------------------------------------------------------------- boletas


def _boletas(f: Filtros) -> Consulta:
    escribano = aliased(Escribano)
    persona = aliased(Persona)
    stmt = select(
        Boleta.numero.label("numero"),
        Boleta.fecha_emision.label("fecha_emision"),
        Boleta.periodo.label("periodo"),
        RegistroNotarial.numero_registro.label("registro"),
        (persona.apellido + ", " + persona.nombre).label("escribano"),
        Boleta.cargo.label("cargo"),
        Boleta.estado.label("estado"),
        Boleta.fecha_vencimiento.label("fecha_vencimiento"),
        Boleta.fecha_pago.label("fecha_pago"),
        Boleta.dias_mora.label("dias_mora"),
        Boleta.total_protocolos.label("total_protocolos"),
        Boleta.aporte_minimo.label("aporte_minimo"),
        Boleta.excedente.label("excedente"),
        Boleta.aporte_medico.label("aporte_medico"),
        Boleta.interes_mora.label("interes_mora"),
        Boleta.total_a_pagar.label("total_a_pagar"),
    ).join(RegistroNotarial, RegistroNotarial.id == Boleta.registro_id)
    # Las boletas del registro (anteriores a las boletas por notario) no tienen escribano.
    stmt = stmt.outerjoin(escribano, escribano.id == Boleta.escribano_id).outerjoin(
        persona, persona.id == escribano.persona_id
    )
    # Sin filtro de estado no se cuentan las anuladas: sumarlas duplicaría importes reemplazados.
    if "estado" in f:
        stmt = stmt.where(Boleta.estado == f["estado"])
    else:
        stmt = stmt.where(Boleta.estado != EstadoBoleta.ANULADA.value)
    if "registro" in f:
        stmt = stmt.where(RegistroNotarial.numero_registro == f["registro"])
    if "escribano" in f:
        like = f"%{f['escribano'].lower()}%"
        stmt = stmt.where(func.lower(persona.apellido + ", " + persona.nombre).like(like))
    if f.get("atraso") == "CON_INTERES":
        stmt = stmt.where(Boleta.interes_mora > 0)
    elif f.get("atraso") == "VENCIDA_IMPAGA":
        stmt = stmt.where(_vencida_impaga())
    stmt = _rango_periodos(stmt, Boleta.periodo, f)
    return stmt.order_by(Boleta.periodo.desc(), Boleta.numero.desc())


def _vencida_impaga() -> ColumnElement[bool]:
    """Pendiente de pago y con el vencimiento del período ya pasado (hoy en San Juan)."""
    return and_(
        Boleta.estado == EstadoBoleta.PENDIENTE.value, Boleta.fecha_vencimiento < today_local()
    )


def _con_atraso() -> ColumnElement[bool]:
    """Pagada con interés por mora, o vencida e impaga."""
    return or_(
        and_(Boleta.estado == EstadoBoleta.PAGADA.value, Boleta.interes_mora > 0),
        _vencida_impaga(),
    )


ATRASO = Filtro(
    "atraso",
    "Atraso",
    TipoFiltro.OPCIONES,
    (
        ("CON_INTERES", "Con interés por mora"),
        ("VENCIDA_IMPAGA", "Vencidas e impagas"),
    ),
)


BOLETAS = Reporte(
    codigo="BOLETAS",
    construir=_boletas,
    titulo="Boletas emitidas",
    descripcion=(
        "Una boleta por escribano y período, con su desglose. Sin filtro de estado no incluye "
        "las anuladas."
    ),
    permiso=Perm.REPORTS_FINANCIAL,
    columnas=(
        Columna("numero", "N°", Tipo.ENTERO),
        Columna("fecha_emision", "Emisión", Tipo.FECHA, visible=False),
        Columna("periodo", "Período", Tipo.PERIODO),
        Columna("registro", "Registro", Tipo.ENTERO),
        Columna("escribano", "Escribano", vacio="Del registro"),
        Columna("cargo", "Cargo", visible=False, vacio="—"),
        Columna("estado", "Estado"),
        Columna("fecha_vencimiento", "Vencimiento", Tipo.FECHA, visible=False),
        Columna("fecha_pago", "Pagar hasta", Tipo.FECHA),
        Columna("dias_mora", "Días de mora", Tipo.ENTERO, visible=False),
        Columna("total_protocolos", "Protocolos", Tipo.MONEDA, total=True, visible=False),
        Columna("aporte_minimo", "Mínimo", Tipo.MONEDA, total=True, visible=False),
        Columna("excedente", "Excedente", Tipo.MONEDA, total=True, visible=False),
        Columna("aporte_medico", "Aporte médico", Tipo.MONEDA, total=True, visible=False),
        Columna("interes_mora", "Interés", Tipo.MONEDA, total=True, visible=False),
        Columna("total_a_pagar", "Total", Tipo.MONEDA, total=True),
    ),
    filtros=(
        *PERIODOS,
        Filtro(
            "estado",
            "Estado",
            TipoFiltro.OPCIONES,
            (
                (EstadoBoleta.PENDIENTE.value, "Pendiente de pago"),
                (EstadoBoleta.PAGADA.value, "Pagada"),
                (EstadoBoleta.ANULADA.value, "Anulada"),
            ),
        ),
        ATRASO,
        Filtro("registro", "N° de registro", TipoFiltro.ENTERO),
        Filtro("escribano", "Escribano", TipoFiltro.TEXTO, ayuda="Apellido o nombre"),
    ),
)

# --------------------------------------------------------------------------- aportes


def _nombre(persona: Any) -> ColumnElement[str]:
    nombre: ColumnElement[str] = persona.apellido + ", " + persona.nombre
    return nombre


def _filtro_escribano(stmt: Consulta, persona: Any, f: Filtros) -> Consulta:
    if "escribano" in f:
        stmt = stmt.where(func.lower(_nombre(persona)).like(f"%{f['escribano'].lower()}%"))
    return stmt


def _suma_si(condicion: ColumnElement[bool], valor: Any) -> ColumnElement[Any]:
    return func.coalesce(func.sum(case((condicion, valor), else_=0)), 0)


PAGADA = Boleta.estado == EstadoBoleta.PAGADA.value
PENDIENTE = Boleta.estado == EstadoBoleta.PENDIENTE.value


def _aportes_periodo(f: Filtros) -> Consulta:
    """Lo declarado y lo pagado de las boletas vigentes (sin las anuladas), por mes o por año."""
    escribano = aliased(Escribano)
    persona = aliased(Persona)
    if f.get("agrupar") == "ANIO":
        clave: ColumnElement[str] = func.substr(Boleta.periodo, 1, 4)
        etiqueta: ColumnElement[str] = clave
    else:
        clave = Boleta.periodo.expression
        etiqueta = func.substr(Boleta.periodo, 6, 2) + "/" + func.substr(Boleta.periodo, 1, 4)
    stmt = (
        select(
            etiqueta.label("periodo"),
            func.count(Boleta.id).label("boletas"),
            func.sum(Boleta.total_en_termino).label("declarado"),
            _suma_si(PAGADA, Boleta.total_a_pagar).label("pagado"),
            _suma_si(PAGADA, Boleta.interes_mora).label("intereses"),
            _suma_si(PENDIENTE, Boleta.total_en_termino).label("impago"),
            func.count(Boleta.id).filter(_con_atraso()).label("con_atraso"),
            func.count(Boleta.id).filter(_vencida_impaga()).label("vencidas_impagas"),
        )
        .join(RegistroNotarial, RegistroNotarial.id == Boleta.registro_id)
        .outerjoin(escribano, escribano.id == Boleta.escribano_id)
        .outerjoin(persona, persona.id == escribano.persona_id)
        .where(Boleta.estado != EstadoBoleta.ANULADA.value)
    )
    if "registro" in f:
        stmt = stmt.where(RegistroNotarial.numero_registro == f["registro"])
    stmt = _filtro_escribano(stmt, persona, f)
    stmt = _rango_periodos(stmt, Boleta.periodo, f)
    return stmt.group_by(clave, etiqueta).order_by(clave.desc())


APORTES_PERIODO = Reporte(
    codigo="APORTES_PERIODO",
    construir=_aportes_periodo,
    titulo="Aportes declarados y pagados",
    descripcion=(
        "Por mes o por año: lo declarado en término, lo pagado (con intereses), los intereses "
        "cobrados, lo impago y las boletas con atraso. Sin las boletas anuladas ni el histórico "
        "del sistema anterior."
    ),
    permiso=Perm.REPORTS_FINANCIAL,
    columnas=(
        Columna("periodo", "Período"),
        Columna("boletas", "Boletas", Tipo.ENTERO, total=True),
        Columna("declarado", "Declarado en término", Tipo.MONEDA, total=True),
        Columna("pagado", "Pagado", Tipo.MONEDA, total=True),
        Columna("intereses", "Intereses cobrados", Tipo.MONEDA, total=True),
        Columna("impago", "Impago", Tipo.MONEDA, total=True),
        Columna("con_atraso", "Con atraso", Tipo.ENTERO, total=True),
        Columna("vencidas_impagas", "Vencidas e impagas", Tipo.ENTERO, total=True, visible=False),
    ),
    filtros=(
        Filtro(
            "agrupar",
            "Agrupar por",
            TipoFiltro.OPCIONES,
            (("MES", "Mes"), ("ANIO", "Año")),
            ayuda="Sin elegir, por mes",
        ),
        *PERIODOS,
        Filtro("registro", "N° de registro", TipoFiltro.ENTERO),
        Filtro("escribano", "Escribano", TipoFiltro.TEXTO, ayuda="Apellido o nombre"),
    ),
)

# --------------------------------------------------------------------------- actos declarados

CATEGORIA_TEXTO = {
    CategoriaActo.ESCRITURA_CON_VALOR.value: "Escritura con valor",
    CategoriaActo.ACTA_O_PODER.value: "Acta o poder",
    CategoriaActo.OTRO_ACTO.value: "Otro acto sin valor",
    CategoriaActo.SIN_EFECTO.value: "Sin efecto",
    CategoriaActo.EXENTO.value: "Exento",
}
PAGO_DDJJ = {
    "PAGADA": "Pagada",
    "PARCIAL": "Pago parcial",
    "PENDIENTE": "Pendiente",
    "SIN_BOLETA": "Sin boleta",
}


def _pago_ddjj(ddjj_id: Any) -> ColumnElement[str]:
    """Pago de las boletas vigentes de la DDJJ: cada escribano paga la suya."""
    vigentes = (
        select(func.count(Boleta.id))
        .where(Boleta.ddjj_id == ddjj_id, Boleta.estado != EstadoBoleta.ANULADA.value)
        .scalar_subquery()
    )
    pagadas = (
        select(func.count(Boleta.id)).where(Boleta.ddjj_id == ddjj_id, PAGADA).scalar_subquery()
    )
    return case(
        (vigentes == 0, "SIN_BOLETA"),
        (pagadas == vigentes, "PAGADA"),
        (pagadas > 0, "PARCIAL"),
        else_="PENDIENTE",
    )


def _actos(f: Filtros) -> Consulta:
    pago = _pago_ddjj(DeclaracionJurada.id)
    stmt = (
        select(
            DeclaracionJurada.periodo.label("periodo"),
            RegistroNotarial.numero_registro.label("registro"),
            _nombre(Persona).label("escribano"),
            Acto.cargo.label("cargo"),
            Acto.tipo_protocolo.label("protocolo"),
            Acto.numero_escritura.label("escritura"),
            Acto.fecha_acto.label("fecha_acto"),
            case(CATEGORIA_TEXTO, value=Acto.categoria, else_=Acto.categoria).label("categoria"),
            Acto.naturaleza.label("naturaleza"),
            Acto.motivo_exencion.label("motivo_exencion"),
            Acto.base_imponible.label("base_imponible"),
            func.coalesce(Acto.aporte, 0).label("aporte"),
            case(PAGO_DDJJ, value=pago, else_=pago).label("pago"),
        )
        .join(DeclaracionJurada, DeclaracionJurada.id == Acto.ddjj_id)
        .join(RegistroNotarial, RegistroNotarial.id == DeclaracionJurada.registro_id)
        .join(Escribano, Escribano.id == Acto.escribano_id)
        .join(Persona, Persona.id == Escribano.persona_id)
        # Solo lo presentado: una DDJJ rectificada fue reemplazada y un borrador no se declaró.
        .where(DeclaracionJurada.estado == EstadoDDJJ.PRESENTADA.value, Acto.is_active.is_(True))
    )
    if "categoria" in f:
        stmt = stmt.where(Acto.categoria == f["categoria"])
    if "naturaleza" in f:
        stmt = stmt.where(func.lower(Acto.naturaleza).like(f"%{f['naturaleza'].lower()}%"))
    if "registro" in f:
        stmt = stmt.where(RegistroNotarial.numero_registro == f["registro"])
    if "pago" in f:
        stmt = stmt.where(pago == f["pago"])
    stmt = _filtro_escribano(stmt, Persona, f)
    stmt = _rango_periodos(stmt, DeclaracionJurada.periodo, f)
    return stmt.order_by(
        DeclaracionJurada.periodo.desc(),
        RegistroNotarial.numero_registro,
        Acto.tipo_protocolo,
        Acto.numero_escritura,
        Acto.orden_en_escritura,
        Acto.id,
    )


ACTOS = Reporte(
    codigo="ACTOS",
    construir=_actos,
    titulo="Actos declarados",
    descripcion=(
        "Cada acto de las declaraciones presentadas, con su base y su aporte, y el pago de las "
        "boletas de esa declaración. Se filtra por tipo de acto, naturaleza y período."
    ),
    permiso=Perm.REPORTS_FINANCIAL,
    columnas=(
        Columna("periodo", "Período", Tipo.PERIODO),
        Columna("registro", "Registro", Tipo.ENTERO),
        Columna("escribano", "Escribano"),
        Columna("cargo", "Cargo", visible=False),
        Columna("protocolo", "Protocolo", visible=False),
        Columna("escritura", "Escritura", Tipo.ENTERO),
        Columna("fecha_acto", "Fecha", Tipo.FECHA),
        Columna("categoria", "Tipo de acto"),
        Columna("naturaleza", "Naturaleza"),
        Columna("motivo_exencion", "Motivo de la exención", visible=False, vacio="—"),
        Columna("base_imponible", "Base imponible", Tipo.MONEDA, total=True),
        Columna("aporte", "Aporte", Tipo.MONEDA, total=True),
        Columna("pago", "Pago de la DDJJ"),
    ),
    filtros=(
        *PERIODOS,
        Filtro(
            "categoria",
            "Tipo de acto",
            TipoFiltro.OPCIONES,
            tuple(CATEGORIA_TEXTO.items()),
        ),
        Filtro("naturaleza", "Naturaleza", TipoFiltro.TEXTO, ayuda="Compraventa, poder, …"),
        Filtro("pago", "Pago de la DDJJ", TipoFiltro.OPCIONES, tuple(PAGO_DDJJ.items())),
        Filtro("registro", "N° de registro", TipoFiltro.ENTERO),
        Filtro("escribano", "Escribano", TipoFiltro.TEXTO, ayuda="Apellido o nombre"),
    ),
)

# --------------------------------------------------------------------------- sin DDJJ o sin pago


def periodo_anterior(hoy: date) -> str:
    """El mes que normalmente se está declarando."""
    anio, mes = (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)
    return f"{anio:04d}-{mes:02d}"


def _limites(periodo: str) -> tuple[date, date]:
    anio, mes = int(periodo[:4]), int(periodo[5:7])
    siguiente = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
    return date(anio, mes, 1), siguiente - timedelta(days=1)


ESTADO_DDJJ_TEXTO = {
    "PRESENTADA": "Presentada",
    "BORRADOR": "En borrador",
    "SIN_DDJJ": "Sin DDJJ",
}
PAGO_TEXTO = {
    "PAGADA": "Pagada",
    "PENDIENTE": "Pendiente de pago",
    "SIN_BOLETA": "Sin boleta",
}


def _sin_ddjj_o_pago(f: Filtros) -> Consulta:
    periodo = f.get("periodo") or periodo_anterior(today_local())
    desde, hasta = _limites(periodo)

    def ddjj_en(estado: EstadoDDJJ) -> ColumnElement[bool]:
        return (
            select(DeclaracionJurada.id)
            .where(
                DeclaracionJurada.registro_id == Adscripcion.registro_id,
                DeclaracionJurada.periodo == periodo,
                DeclaracionJurada.estado == estado.value,
            )
            .exists()
        )

    def boleta_en(estado: EstadoBoleta) -> ColumnElement[bool]:
        # La del escribano, o la del registro entero (boletas anteriores a las por notario).
        return (
            select(Boleta.id)
            .where(
                Boleta.registro_id == Adscripcion.registro_id,
                Boleta.periodo == periodo,
                Boleta.estado == estado.value,
                or_(Boleta.escribano_id == Escribano.id, Boleta.escribano_id.is_(None)),
            )
            .exists()
        )

    estado_ddjj = case(
        (ddjj_en(EstadoDDJJ.PRESENTADA), "PRESENTADA"),
        (ddjj_en(EstadoDDJJ.BORRADOR), "BORRADOR"),
        else_="SIN_DDJJ",
    )
    pago = case(
        (boleta_en(EstadoBoleta.PAGADA), "PAGADA"),
        (boleta_en(EstadoBoleta.PENDIENTE), "PENDIENTE"),
        else_="SIN_BOLETA",
    )
    licencia = (
        select(Licencia.id)
        .where(
            Licencia.escribano_id == Escribano.id,
            Licencia.anulada.is_(False),
            Licencia.fecha_desde <= hasta,
            or_(Licencia.fecha_hasta.is_(None), Licencia.fecha_hasta >= desde),
        )
        .exists()
    )
    stmt = (
        select(
            literal(periodo).label("periodo"),
            Escribano.matricula_numero.label("matricula"),
            _nombre(Persona).label("escribano"),
            RegistroNotarial.numero_registro.label("registro"),
            case(CARGO_TEXTO, value=Adscripcion.cargo, else_=Adscripcion.cargo).label("cargo"),
            case(ESTADO_DDJJ_TEXTO, value=estado_ddjj, else_=estado_ddjj).label("ddjj"),
            case(PAGO_TEXTO, value=pago, else_=pago).label("pago"),
            case((licencia, "Sí"), else_="—").label("licencia"),
            Escribano.estado_matricula.label("estado_matricula"),
            RegistroNotarial.departamento.label("departamento"),
            Persona.email.label("email"),
            Persona.telefono.label("telefono"),
        )
        .select_from(Adscripcion)
        .join(Escribano, Escribano.id == Adscripcion.escribano_id)
        .join(Persona, Persona.id == Escribano.persona_id)
        .join(RegistroNotarial, RegistroNotarial.id == Adscripcion.registro_id)
        # Titulares y adscriptos con el cargo durante el período (quien está a cargo declara en
        # la DDJJ del registro y no tiene boleta propia obligatoria).
        .where(
            Adscripcion.cargo.in_((Cargo.TITULAR.value, Cargo.ADSCRIPTO.value)),
            Adscripcion.fecha_desde <= hasta,
            or_(Adscripcion.fecha_hasta.is_(None), Adscripcion.fecha_hasta >= desde),
        )
    )
    situacion = f.get("situacion", "PENDIENTES")
    if situacion == "SIN_DDJJ":
        stmt = stmt.where(estado_ddjj != "PRESENTADA")
    elif situacion == "SIN_PAGO":
        stmt = stmt.where(estado_ddjj == "PRESENTADA", pago != "PAGADA")
    elif situacion == "PENDIENTES":
        stmt = stmt.where(or_(estado_ddjj != "PRESENTADA", pago != "PAGADA"))
    if "registro" in f:
        stmt = stmt.where(RegistroNotarial.numero_registro == f["registro"])
    if "departamento" in f:
        stmt = stmt.where(RegistroNotarial.departamento == f["departamento"])
    return stmt.order_by(
        RegistroNotarial.numero_registro, Adscripcion.cargo.desc(), _nombre(Persona), Escribano.id
    )


SIN_DDJJ_O_PAGO = Reporte(
    codigo="SIN_DDJJ_O_PAGO",
    construir=_sin_ddjj_o_pago,
    titulo="Notarios sin DDJJ o sin pago",
    descripcion=(
        "Titulares y adscriptos de un período cuyo registro no presentó la DDJJ, o que no "
        "pagaron su boleta. Sin elegir período, el mes anterior. La licencia se muestra pero no "
        "los excluye: la Caja decide si un escribano en licencia aporta."
    ),
    permiso=Perm.REPORTS_FINANCIAL,
    sensible=True,
    columnas=(
        Columna("periodo", "Período", Tipo.PERIODO),
        Columna("matricula", "Matrícula", Tipo.ENTERO, vacio=A_COMPLETAR),
        Columna("escribano", "Escribano"),
        Columna("registro", "Registro", Tipo.ENTERO),
        Columna("cargo", "Cargo"),
        Columna("ddjj", "DDJJ del registro"),
        Columna("pago", "Su boleta"),
        Columna("licencia", "En licencia"),
        Columna("estado_matricula", "Matrícula", visible=False),
        Columna("departamento", "Departamento", visible=False),
        Columna("email", "Correo", visible=False),
        Columna("telefono", "Teléfono", visible=False),
    ),
    filtros=(
        Filtro("periodo", "Período", TipoFiltro.PERIODO, ayuda="Sin elegir, el mes anterior"),
        Filtro(
            "situacion",
            "Mostrar",
            TipoFiltro.OPCIONES,
            (
                ("PENDIENTES", "Sin DDJJ o sin pago"),
                ("SIN_DDJJ", "Solo sin DDJJ presentada"),
                ("SIN_PAGO", "Solo con DDJJ y sin pago"),
                ("TODOS", "Todos, también los al día"),
            ),
            ayuda="Sin elegir, sin DDJJ o sin pago",
        ),
        Filtro("registro", "N° de registro", TipoFiltro.ENTERO),
        Filtro(
            "departamento",
            "Departamento",
            TipoFiltro.OPCIONES,
            tuple((d, d) for d in DEPARTAMENTOS_SAN_JUAN),
        ),
    ),
)

# --------------------------------------------------------------------------- mis aportes


SIN_ESCRIBANO = uuid.UUID(int=0)


def _mis_aportes(f: Filtros) -> Consulta:
    stmt = (
        select(
            Boleta.periodo.label("periodo"),
            Boleta.numero.label("boleta"),
            RegistroNotarial.numero_registro.label("registro"),
            Boleta.estado.label("estado"),
            Boleta.fecha_vencimiento.label("fecha_vencimiento"),
            Boleta.total_protocolos.label("total_protocolos"),
            Boleta.total_en_termino.label("aporte"),
            Boleta.interes_mora.label("intereses"),
            case((PAGADA, Boleta.total_a_pagar), else_=0).label("pagado"),
            case((PENDIENTE, Boleta.total_en_termino), else_=0).label("impago"),
        )
        .join(RegistroNotarial, RegistroNotarial.id == Boleta.registro_id)
        .where(
            # Sin escribano (p. ej. al armar la consulta sin sesión) no hay filas.
            Boleta.escribano_id == f.get(ESCRIBANO_PROPIO, SIN_ESCRIBANO),
            Boleta.estado != EstadoBoleta.ANULADA.value,
        )
    )
    if "estado" in f:
        stmt = stmt.where(Boleta.estado == f["estado"])
    stmt = _rango_periodos(stmt, Boleta.periodo, f)
    return stmt.order_by(Boleta.periodo.desc(), Boleta.numero.desc())


MIS_APORTES = Reporte(
    codigo="MIS_APORTES",
    construir=_mis_aportes,
    titulo="Mis aportes",
    descripcion=(
        "Tus boletas vigentes y el total de aportes del período que elijas: lo declarado en "
        "término, los intereses, lo pagado y lo que queda por pagar. No incluye el histórico del "
        "sistema anterior."
    ),
    permiso=Perm.BOLETAS_READ_OWN,
    propio=True,
    columnas=(
        Columna("periodo", "Período", Tipo.PERIODO),
        Columna("boleta", "Boleta", Tipo.ENTERO),
        Columna("registro", "Registro", Tipo.ENTERO, visible=False),
        Columna("estado", "Estado"),
        Columna("fecha_vencimiento", "Vencimiento", Tipo.FECHA, visible=False),
        Columna("total_protocolos", "Protocolos", Tipo.MONEDA, total=True, visible=False),
        Columna("aporte", "Aporte del mes", Tipo.MONEDA, total=True),
        Columna("intereses", "Intereses", Tipo.MONEDA, total=True),
        Columna("pagado", "Pagado", Tipo.MONEDA, total=True),
        Columna("impago", "Por pagar", Tipo.MONEDA, total=True),
    ),
    filtros=(
        *PERIODOS,
        Filtro(
            "estado",
            "Estado",
            TipoFiltro.OPCIONES,
            (
                (EstadoBoleta.PENDIENTE.value, "Pendiente de pago"),
                (EstadoBoleta.PAGADA.value, "Pagada"),
            ),
        ),
    ),
)

# --------------------------------------------------------------------------- pagos


def _pagos(f: Filtros) -> Consulta:
    operador = aliased(User)
    stmt = (
        select(
            Conciliacion.created_at.label("fecha"),
            Boleta.numero.label("boleta"),
            RegistroNotarial.numero_registro.label("registro"),
            Boleta.periodo.label("periodo"),
            Conciliacion.resultado.label("resultado"),
            Comprobante.fecha_transferencia.label("fecha_transferencia"),
            Comprobante.numero_operacion.label("numero_operacion"),
            Comprobante.importe_declarado.label("importe_declarado"),
            Conciliacion.importe_confirmado.label("importe_confirmado"),
            Conciliacion.fecha_acreditacion.label("fecha_acreditacion"),
            Conciliacion.identificador_extracto.label("extracto"),
            Conciliacion.observaciones.label("observaciones"),
            operador.email.label("operador"),
        )
        .join(Comprobante, Comprobante.id == Conciliacion.comprobante_id)
        .join(Boleta, Boleta.id == Conciliacion.boleta_id)
        .join(RegistroNotarial, RegistroNotarial.id == Boleta.registro_id)
        .join(operador, operador.id == Conciliacion.operador_user_id)
    )
    if "resultado" in f:
        stmt = stmt.where(Conciliacion.resultado == f["resultado"])
    stmt = _rango_fechas(stmt, Conciliacion.created_at, f)
    return stmt.order_by(Conciliacion.created_at.desc(), Conciliacion.id)


PAGOS = Reporte(
    codigo="PAGOS",
    construir=_pagos,
    titulo="Pagos y conciliaciones",
    descripcion="Cada revisión de Tesorería: pagos confirmados y comprobantes rechazados.",
    permiso=Perm.REPORTS_FINANCIAL,
    columnas=(
        Columna("fecha", "Revisado", Tipo.FECHA_HORA),
        Columna("boleta", "Boleta", Tipo.ENTERO),
        Columna("registro", "Registro", Tipo.ENTERO),
        Columna("periodo", "Período", Tipo.PERIODO, visible=False),
        Columna("resultado", "Resultado"),
        Columna("fecha_transferencia", "Transferencia", Tipo.FECHA, visible=False),
        Columna("numero_operacion", "N° de operación", visible=False),
        Columna("importe_declarado", "Declarado", Tipo.MONEDA, visible=False),
        Columna("importe_confirmado", "Acreditado", Tipo.MONEDA, total=True),
        Columna("fecha_acreditacion", "Acreditación", Tipo.FECHA),
        Columna("extracto", "Extracto", visible=False),
        Columna("observaciones", "Observaciones o motivo", visible=False),
        Columna("operador", "Operador", visible=False),
    ),
    filtros=(
        *FECHAS,
        Filtro(
            "resultado",
            "Resultado",
            TipoFiltro.OPCIONES,
            (
                (ResultadoConciliacion.APROBADO.value, "Pago confirmado"),
                (ResultadoConciliacion.RECHAZADO.value, "Rechazado"),
            ),
        ),
    ),
)

# --------------------------------------------------------------------------- recaudación


def _recaudacion(f: Filtros) -> Consulta:
    stmt = select(
        Boleta.periodo.label("periodo"),
        func.count(Boleta.id).label("boletas"),
        func.sum(Boleta.total_protocolos).label("total_protocolos"),
        func.sum(Boleta.aporte_minimo).label("aporte_minimo"),
        func.sum(Boleta.excedente).label("excedente"),
        func.sum(Boleta.aporte_medico).label("aporte_medico"),
        func.sum(Boleta.interes_mora).label("interes_mora"),
        func.sum(Boleta.total_a_pagar).label("total_cobrado"),
    ).where(Boleta.estado == EstadoBoleta.PAGADA.value)
    stmt = _rango_periodos(stmt, Boleta.periodo, f)
    return stmt.group_by(Boleta.periodo).order_by(Boleta.periodo.desc())


RECAUDACION = Reporte(
    codigo="RECAUDACION",
    construir=_recaudacion,
    titulo="Recaudación por período",
    descripcion="Boletas pagadas (confirmadas por Tesorería), agrupadas por período declarado.",
    permiso=Perm.REPORTS_FINANCIAL,
    columnas=(
        Columna("periodo", "Período", Tipo.PERIODO),
        Columna("boletas", "Boletas", Tipo.ENTERO, total=True),
        Columna("total_protocolos", "Protocolos", Tipo.MONEDA, total=True, visible=False),
        Columna("aporte_minimo", "Mínimo", Tipo.MONEDA, total=True),
        Columna("excedente", "Excedente", Tipo.MONEDA, total=True),
        Columna("aporte_medico", "Aporte médico", Tipo.MONEDA, total=True),
        Columna("interes_mora", "Interés", Tipo.MONEDA, total=True, visible=False),
        Columna("total_cobrado", "Total cobrado", Tipo.MONEDA, total=True),
    ),
    filtros=PERIODOS,
)

# --------------------------------------------------------------------------- auditoría


def _auditoria(f: Filtros) -> Consulta:
    actor = aliased(User)
    target = aliased(User)
    stmt = (
        select(
            AuditSecurityLog.event_timestamp.label("fecha"),
            AuditSecurityLog.event_type.label("evento"),
            AuditSecurityLog.severity.label("severidad"),
            actor.email.label("actor"),
            target.email.label("afectado"),
            cast(AuditSecurityLog.ip_address, String).label("ip"),
            cast(AuditSecurityLog.old_value, String).label("valor_anterior"),
            cast(AuditSecurityLog.new_value, String).label("valor_nuevo"),
            cast(AuditSecurityLog.details, String).label("detalle"),
            AuditSecurityLog.correlation_id.label("correlation_id"),
        )
        .outerjoin(actor, actor.id == AuditSecurityLog.actor_user_id)
        .outerjoin(target, target.id == AuditSecurityLog.target_user_id)
    )
    if "evento" in f:
        stmt = stmt.where(AuditSecurityLog.event_type == f["evento"].upper())
    if "severidad" in f:
        stmt = stmt.where(AuditSecurityLog.severity == f["severidad"])
    stmt = _rango_fechas(stmt, AuditSecurityLog.event_timestamp, f)
    return stmt.order_by(AuditSecurityLog.event_timestamp.desc(), AuditSecurityLog.id)


AUDITORIA = Reporte(
    codigo="AUDITORIA",
    construir=_auditoria,
    titulo="Registro de auditoría",
    descripcion="Eventos de seguridad y acciones sensibles, con valor anterior y nuevo.",
    permiso=Perm.AUDIT_READ,
    sensible=True,
    columnas=(
        Columna("fecha", "Fecha", Tipo.FECHA_HORA),
        Columna("evento", "Evento"),
        Columna("severidad", "Severidad"),
        Columna("actor", "Actor"),
        Columna("afectado", "Afectado", visible=False),
        Columna("ip", "IP", visible=False),
        Columna("valor_anterior", "Valor anterior", visible=False),
        Columna("valor_nuevo", "Valor nuevo", visible=False),
        Columna("detalle", "Detalle", visible=False),
        Columna("correlation_id", "Correlation ID", visible=False),
    ),
    filtros=(
        *FECHAS,
        Filtro("evento", "Evento", TipoFiltro.TEXTO, ayuda="Código exacto, p. ej. LOGIN_FAILED"),
        Filtro(
            "severidad",
            "Severidad",
            TipoFiltro.OPCIONES,
            tuple((s.value, s.value.capitalize()) for s in Severity),
        ),
    ),
)

# --------------------------------------------------------------------------- IA asistencial

TIPO_SUGERENCIA_TEXTO = {
    TipoSugerencia.EXTRACCION_MINUTA.value: "Minuta → acto de DDJJ",
    TipoSugerencia.OCR_DNI.value: "DNI → alta en el padrón",
}
ESTADO_SUGERENCIA_TEXTO = {
    EstadoSugerencia.SUGERIDO_POR_IA.value: "Sugerido por IA (sin ratificar)",
    EstadoSugerencia.RATIFICADA.value: "Ratificada",
    EstadoSugerencia.DESCARTADA.value: "Descartada",
}


def _sugerencias_ia(f: Filtros) -> Consulta:
    solicito = aliased(User)
    resolvio = aliased(User)
    stmt = (
        select(
            Sugerencia.created_at.label("fecha"),
            case(TIPO_SUGERENCIA_TEXTO, value=Sugerencia.tipo).label("tipo"),
            case(ESTADO_SUGERENCIA_TEXTO, value=Sugerencia.estado).label("estado"),
            (Sugerencia.motor + " " + Sugerencia.motor_version).label("motor"),
            cast(Sugerencia.confianza, String).label("confianza"),
            cast(func.jsonb_array_length(Sugerencia.salida["alertas"]), Integer).label("alertas"),
            case(
                (Sugerencia.campos_modificados.is_(None), None),
                (func.jsonb_array_length(Sugerencia.campos_modificados) > 0, "Sí"),
                else_="No",
            ).label("corregida"),
            # ["folio", "naturaleza"] → folio, naturaleza
            func.translate(cast(Sugerencia.campos_modificados, String), '[]"', "").label(
                "campos_corregidos"
            ),
            solicito.email.label("solicito"),
            resolvio.email.label("resolvio"),
            Sugerencia.resuelto_en.label("resuelto_en"),
            Sugerencia.tiempo_ms.label("tiempo_ms"),
            Sugerencia.id.label("id"),
        )
        .join(solicito, solicito.id == Sugerencia.solicitado_por_user_id)
        .outerjoin(resolvio, resolvio.id == Sugerencia.resuelto_por_user_id)
    )
    if "tipo" in f:
        stmt = stmt.where(Sugerencia.tipo == f["tipo"])
    if "estado" in f:
        stmt = stmt.where(Sugerencia.estado == f["estado"])
    stmt = _rango_fechas(stmt, Sugerencia.created_at, f)
    return stmt.order_by(Sugerencia.created_at.desc(), Sugerencia.id)


SUGERENCIAS_IA = Reporte(
    codigo="SUGERENCIAS_IA",
    construir=_sugerencias_ia,
    titulo="Sugerencias de IA",
    descripcion="Qué propuso cada motor asistencial, con qué confianza, quién lo ratificó o "
    "descartó y qué campos corrigió (Human in Command).",
    permiso=Perm.AUDIT_READ,
    sensible=True,
    columnas=(
        Columna("fecha", "Fecha", Tipo.FECHA_HORA),
        Columna("tipo", "Tipo"),
        Columna("estado", "Estado"),
        Columna("motor", "Motor"),
        Columna("confianza", "Confianza"),
        Columna("alertas", "Alertas", Tipo.ENTERO, total=True),
        Columna("corregida", "Corregida"),
        Columna("campos_corregidos", "Campos corregidos"),
        Columna("solicito", "Pidió y revisó"),
        Columna("resolvio", "Resolvió", visible=False),
        Columna("resuelto_en", "Resuelta el", Tipo.FECHA_HORA, visible=False),
        Columna("tiempo_ms", "Tiempo (ms)", Tipo.ENTERO, visible=False),
        Columna("id", "Id", visible=False),
    ),
    filtros=(
        *FECHAS,
        Filtro("tipo", "Tipo", TipoFiltro.OPCIONES, tuple(TIPO_SUGERENCIA_TEXTO.items())),
        Filtro("estado", "Estado", TipoFiltro.OPCIONES, tuple(ESTADO_SUGERENCIA_TEXTO.items())),
    ),
)

# --------------------------------------------------------------------------- histórico migrado


def _boletas_historicas(f: Filtros) -> Consulta:
    pagado = (
        select(func.coalesce(func.sum(HistoricoPago.importe), 0))
        .where(HistoricoPago.boleta_id == HistoricoBoleta.id)
        .correlate(HistoricoBoleta)
        .scalar_subquery()
    )
    anulada = HistoricoBoleta.estado == EstadoBoletaHistorica.ANULADA.value
    stmt = select(
        RegistroNotarial.numero_registro.label("registro"),
        HistoricoBoleta.periodo.label("periodo"),
        HistoricoBoleta.numero_boleta.label("numero_boleta"),
        HistoricoBoleta.fecha_emision.label("fecha_emision"),
        HistoricoBoleta.fecha_vencimiento.label("fecha_vencimiento"),
        HistoricoBoleta.estado.label("estado"),
        HistoricoBoleta.importe.label("importe"),
        pagado.label("pagado"),
        case((anulada, 0), else_=HistoricoBoleta.importe - pagado).label("saldo"),
        HistoricoBoleta.codigo_legado.label("codigo_legado"),
    ).join(RegistroNotarial, RegistroNotarial.id == HistoricoBoleta.registro_id)
    if "estado" in f:
        stmt = stmt.where(HistoricoBoleta.estado == f["estado"])
    if "registro" in f:
        stmt = stmt.where(RegistroNotarial.numero_registro == f["registro"])
    stmt = _rango_periodos(stmt, HistoricoBoleta.periodo, f)
    return stmt.order_by(
        RegistroNotarial.numero_registro, HistoricoBoleta.periodo, HistoricoBoleta.id
    )


BOLETAS_HISTORICAS = Reporte(
    codigo="BOLETAS_HISTORICAS",
    construir=_boletas_historicas,
    titulo="Boletas del sistema anterior",
    descripcion="Histórico migrado, de solo lectura: importe, lo pagado y el saldo de cada "
    "boleta. Las anuladas no tienen saldo. Los créditos a favor del escribano no se imputan a "
    "boletas: restan del saldo del registro y se consultan en «Créditos del sistema anterior».",
    permiso=Perm.REPORTS_FINANCIAL,
    columnas=(
        Columna("registro", "Registro", Tipo.ENTERO),
        Columna("periodo", "Período", Tipo.PERIODO),
        Columna("numero_boleta", "N° de boleta", visible=False),
        Columna("fecha_emision", "Emisión", Tipo.FECHA, visible=False),
        Columna("fecha_vencimiento", "Vencimiento", Tipo.FECHA),
        Columna("estado", "Estado"),
        Columna("importe", "Importe", Tipo.MONEDA, total=True),
        Columna("pagado", "Pagado", Tipo.MONEDA, total=True),
        Columna("saldo", "Saldo", Tipo.MONEDA, total=True),
        Columna("codigo_legado", "Código en el sistema anterior", visible=False),
    ),
    filtros=(
        *PERIODOS,
        Filtro(
            "estado",
            "Estado",
            TipoFiltro.OPCIONES,
            (
                (EstadoBoletaHistorica.IMPAGA.value, "Impaga"),
                (EstadoBoletaHistorica.PAGADA.value, "Pagada"),
                (EstadoBoletaHistorica.ANULADA.value, "Anulada"),
            ),
        ),
        Filtro("registro", "N° de registro", TipoFiltro.ENTERO),
    ),
)

# --------------------------------------------------------------------------- puntos (Ley 7231)


def _puntos_ejercicios(f: Filtros) -> Consulta:
    afiliados = (
        select(
            PuntosAfiliado.ejercicio_id.label("ejercicio_id"),
            func.count().label("filas"),
            func.sum(PuntosAfiliado.aportes).label("aportes"),
            func.sum(PuntosAfiliado.puntos).label("puntos"),
            func.count(PuntosAfiliado.escribano_id).label("vinculadas"),
        )
        .group_by(PuntosAfiliado.ejercicio_id)
        .subquery()
    )
    stmt = select(
        Ejercicio.anio.label("anio"),
        Ejercicio.fecha_inicio.label("fecha_inicio"),
        Ejercicio.fecha_cierre.label("fecha_cierre"),
        Ejercicio.total_aportes.label("total_aportes"),
        func.coalesce(afiliados.c.aportes, 0).label("suma_aportes"),
        Ejercicio.cantidad_afiliados.label("cantidad_afiliados"),
        Ejercicio.aporte_medio.label("aporte_medio"),
        func.coalesce(afiliados.c.puntos, 0).label("suma_puntos"),
        func.coalesce(afiliados.c.filas, 0).label("con_puntos"),
        (func.coalesce(afiliados.c.filas, 0) - func.coalesce(afiliados.c.vinculadas, 0)).label(
            "sin_vincular"
        ),
        Ejercicio.origen.label("origen"),
    ).outerjoin(afiliados, afiliados.c.ejercicio_id == Ejercicio.id)
    if "anio_desde" in f:
        stmt = stmt.where(Ejercicio.anio >= f["anio_desde"])
    if "anio_hasta" in f:
        stmt = stmt.where(Ejercicio.anio <= f["anio_hasta"])
    return stmt.order_by(Ejercicio.anio.desc())


PUNTOS_EJERCICIOS = Reporte(
    codigo="PUNTOS_EJERCICIOS",
    construir=_puntos_ejercicios,
    titulo="Aportes y puntos por ejercicio",
    descripcion="Ley 7231: total de aportes, afiliados, aporte medio y suma de puntos de cada "
    "ejercicio (1/9 al 31/8, por año de cierre), según la planilla histórica de la Caja.",
    permiso=Perm.PUNTOS_READ_ALL,
    columnas=(
        Columna("anio", "Ejercicio", Tipo.ENTERO),
        Columna("fecha_inicio", "Inicio", Tipo.FECHA, visible=False),
        Columna("fecha_cierre", "Cierre", Tipo.FECHA, visible=False),
        Columna("total_aportes", "Total de aportes", Tipo.MONEDA, total=True),
        Columna("suma_aportes", "Suma por afiliado", Tipo.MONEDA, total=True, visible=False),
        Columna("cantidad_afiliados", "Afiliados", Tipo.DECIMAL, decimales=4),
        Columna("aporte_medio", "Aporte medio", Tipo.DECIMAL, decimales=6),
        Columna("suma_puntos", "Suma de puntos", Tipo.DECIMAL, decimales=6),
        Columna("con_puntos", "Afiliados con puntos", Tipo.ENTERO, visible=False),
        Columna("sin_vincular", "Sin vincular", Tipo.ENTERO, total=True),
        Columna("origen", "Origen", Tipo.TEXTO, visible=False),
    ),
    filtros=(
        Filtro("anio_desde", "Ejercicio desde", TipoFiltro.ENTERO),
        Filtro("anio_hasta", "Ejercicio hasta", TipoFiltro.ENTERO),
    ),
)


def _creditos_historicos(f: Filtros) -> Consulta:
    stmt = select(
        RegistroNotarial.numero_registro.label("registro"),
        HistoricoCredito.fecha.label("fecha"),
        HistoricoCredito.periodo.label("periodo"),
        HistoricoCredito.concepto.label("concepto"),
        HistoricoCredito.importe.label("importe"),
        HistoricoCredito.codigo_legado.label("codigo_legado"),
    ).join(RegistroNotarial, RegistroNotarial.id == HistoricoCredito.registro_id)
    if "registro" in f:
        stmt = stmt.where(RegistroNotarial.numero_registro == f["registro"])
    # Fecha calendario del crédito (no es un timestamp: se compara tal cual).
    if "fecha_desde" in f:
        stmt = stmt.where(HistoricoCredito.fecha >= f["fecha_desde"])
    if "fecha_hasta" in f:
        stmt = stmt.where(HistoricoCredito.fecha <= f["fecha_hasta"])
    stmt = _rango_periodos(stmt, HistoricoCredito.periodo, f)
    return stmt.order_by(
        RegistroNotarial.numero_registro, HistoricoCredito.fecha, HistoricoCredito.id
    )


CREDITOS_HISTORICOS = Reporte(
    codigo="CREDITOS_HISTORICOS",
    construir=_creditos_historicos,
    titulo="Créditos del sistema anterior",
    descripcion="Histórico migrado, de solo lectura: créditos a favor del escribano (casi "
    "todos diferencias de inspección). Restan del saldo del registro. Filtrar por período "
    "deja afuera los créditos sin período.",
    permiso=Perm.REPORTS_FINANCIAL,
    columnas=(
        Columna("registro", "Registro", Tipo.ENTERO),
        Columna("fecha", "Fecha", Tipo.FECHA),
        Columna("periodo", "Período", Tipo.PERIODO),
        Columna("concepto", "Concepto"),
        Columna("importe", "Importe a favor", Tipo.MONEDA, total=True),
        Columna("codigo_legado", "Código en el sistema anterior", visible=False),
    ),
    filtros=(
        Filtro("fecha_desde", "Fecha desde", TipoFiltro.FECHA),
        Filtro("fecha_hasta", "Fecha hasta", TipoFiltro.FECHA),
        *PERIODOS,
        Filtro("registro", "N° de registro", TipoFiltro.ENTERO),
    ),
)


REPORTES: dict[str, Reporte] = {
    r.codigo: r
    for r in (
        ESCRIBANOS,
        ACTOS,
        BOLETAS,
        APORTES_PERIODO,
        SIN_DDJJ_O_PAGO,
        PAGOS,
        RECAUDACION,
        BOLETAS_HISTORICAS,
        CREDITOS_HISTORICOS,
        AUDITORIA,
        SUGERENCIAS_IA,
        PUNTOS_EJERCICIOS,
        MIS_APORTES,
    )
}
