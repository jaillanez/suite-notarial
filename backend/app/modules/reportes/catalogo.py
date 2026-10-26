"""Catálogo de reportes. Cada consulta etiqueta sus columnas con las `key` declaradas y fija un
orden total (con desempate por id) para que paginar y exportar den exactamente las mismas filas."""

from datetime import date
from typing import Any

from sqlalchemy import Date, Integer, String, and_, case, cast, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.common.audit import AuditSecurityLog, Severity
from app.common.dates import LOCAL_TZ
from app.modules.ddjj.catalog import EstadoBoleta
from app.modules.ddjj.models import Boleta
from app.modules.ia.catalog import EstadoSugerencia, TipoSugerencia
from app.modules.ia.models import Sugerencia
from app.modules.iam.catalog import Perm
from app.modules.iam.models import User
from app.modules.migracion.catalog import EstadoBoletaHistorica
from app.modules.migracion.models import HistoricoBoleta, HistoricoPago
from app.modules.padron.catalog import DEPARTAMENTOS_SAN_JUAN, Cargo, EstadoMatricula
from app.modules.padron.models import Adscripcion, Escribano, Persona, RegistroNotarial
from app.modules.pagos.catalog import ResultadoConciliacion
from app.modules.pagos.models import Comprobante, Conciliacion
from app.modules.reportes.framework import (
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
        Columna("matricula", "Matrícula", Tipo.ENTERO),
        Columna("apellido_nombre", "Apellido y nombre"),
        Columna("cuit", "CUIT", Tipo.CUIT),
        Columna("estado", "Estado"),
        Columna("registro", "Registro", Tipo.ENTERO),
        Columna("cargo", "Cargo"),
        Columna("departamento", "Departamento", visible=False),
        Columna("fecha_matriculacion", "Matriculación", Tipo.FECHA, visible=False),
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
    stmt = select(
        Boleta.numero.label("numero"),
        Boleta.fecha_emision.label("fecha_emision"),
        Boleta.periodo.label("periodo"),
        RegistroNotarial.numero_registro.label("registro"),
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
    # Sin filtro de estado no se cuentan las anuladas: sumarlas duplicaría importes reemplazados.
    if "estado" in f:
        stmt = stmt.where(Boleta.estado == f["estado"])
    else:
        stmt = stmt.where(Boleta.estado != EstadoBoleta.ANULADA.value)
    if "registro" in f:
        stmt = stmt.where(RegistroNotarial.numero_registro == f["registro"])
    stmt = _rango_periodos(stmt, Boleta.periodo, f)
    return stmt.order_by(Boleta.periodo.desc(), Boleta.numero.desc())


BOLETAS = Reporte(
    codigo="BOLETAS",
    construir=_boletas,
    titulo="Boletas emitidas",
    descripcion="Boletas con su desglose. Sin filtro de estado no incluye las anuladas.",
    permiso=Perm.REPORTS_FINANCIAL,
    columnas=(
        Columna("numero", "N°", Tipo.ENTERO),
        Columna("fecha_emision", "Emisión", Tipo.FECHA, visible=False),
        Columna("periodo", "Período", Tipo.PERIODO),
        Columna("registro", "Registro", Tipo.ENTERO),
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
        Filtro("registro", "N° de registro", TipoFiltro.ENTERO),
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
    "boleta. Las anuladas no tienen saldo.",
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


REPORTES: dict[str, Reporte] = {
    r.codigo: r
    for r in (
        ESCRIBANOS,
        BOLETAS,
        PAGOS,
        RECAUDACION,
        BOLETAS_HISTORICAS,
        AUDITORIA,
        SUGERENCIAS_IA,
    )
}
