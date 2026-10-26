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
from app.modules.padron.models import (
    Adscripcion,
    Circunscripcion,
    Escribano,
    HistorialEstado,
    Persona,
    RegistroNotarial,
)
from app.modules.pagos.models import Comprobante, Conciliacion
from app.modules.parametros.models import Concepto, Vigencia
from app.modules.prestamos.models import CuotaPrestamo, Linea, Prestamo

__all__ = [
    "Acto",
    "Adscripcion",
    "AuditSecurityLog",
    "Autoridad",
    "Base",
    "Boleta",
    "Circunscripcion",
    "Comprobante",
    "Concepto",
    "Conciliacion",
    "CuotaPrestamo",
    "DeclaracionJurada",
    "Documento",
    "DocumentoVersion",
    "Escribano",
    "HistorialEstado",
    "Linea",
    "Novedad",
    "PasswordResetToken",
    "Permission",
    "Persona",
    "Prestamo",
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
