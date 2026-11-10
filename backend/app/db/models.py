"""Registro central de modelos para Alembic.

Cada módulo que defina modelos debe importarse acá para que `--autogenerate` los detecte.
"""

from app.common.audit import AuditSecurityLog
from app.db.base import Base
from app.modules.cms.models import Autoridad, Documento, DocumentoVersion, Novedad
from app.modules.ddjj.models import Acto, Boleta, DeclaracionJurada, Vencimiento
from app.modules.ia.models import Sugerencia
from app.modules.iam.models import (
    PasswordResetToken,
    Permission,
    RecoveryCode,
    Role,
    RolePermission,
    User,
    UserRole,
    UserSession,
)
from app.modules.migracion.models import (
    Conformidad,
    Corrida,
    HistoricoBoleta,
    HistoricoCredito,
    HistoricoPago,
    Mapeo,
    ObservacionMigracion,
)
from app.modules.padron.models import (
    Adscripcion,
    AjustesPadron,
    Circunscripcion,
    DesignacionACargo,
    Escribano,
    HistorialEstado,
    Persona,
    RegistroNotarial,
)
from app.modules.pagos.models import Comprobante, Conciliacion, PagoMercadoPago
from app.modules.parametros.models import Concepto, Vigencia
from app.modules.prestamos.models import CuotaPrestamo, DocumentoPrestamo, Linea, Prestamo
from app.modules.previsional.models import Ejercicio, PuntosAfiliado

__all__ = [
    "Acto",
    "Adscripcion",
    "AjustesPadron",
    "AuditSecurityLog",
    "Autoridad",
    "Base",
    "Boleta",
    "Circunscripcion",
    "Comprobante",
    "Concepto",
    "Conciliacion",
    "Conformidad",
    "Corrida",
    "CuotaPrestamo",
    "DeclaracionJurada",
    "DesignacionACargo",
    "Documento",
    "DocumentoPrestamo",
    "DocumentoVersion",
    "Ejercicio",
    "Escribano",
    "HistorialEstado",
    "HistoricoBoleta",
    "HistoricoCredito",
    "HistoricoPago",
    "Linea",
    "Mapeo",
    "Novedad",
    "ObservacionMigracion",
    "PagoMercadoPago",
    "PasswordResetToken",
    "Permission",
    "Persona",
    "Prestamo",
    "PuntosAfiliado",
    "RecoveryCode",
    "RegistroNotarial",
    "Role",
    "RolePermission",
    "Sugerencia",
    "User",
    "UserRole",
    "UserSession",
    "Vencimiento",
    "Vigencia",
]
