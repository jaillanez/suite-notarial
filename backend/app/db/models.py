"""Registro central de modelos para Alembic.

Cada módulo que defina modelos debe importarse acá para que `--autogenerate` los detecte.
"""

from app.common.audit import AuditSecurityLog
from app.db.base import Base
from app.modules.ddjj.models import Acto, Boleta, DeclaracionJurada, Vencimiento
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

__all__ = [
    "Acto",
    "Adscripcion",
    "AuditSecurityLog",
    "Base",
    "Boleta",
    "Circunscripcion",
    "Comprobante",
    "Concepto",
    "Conciliacion",
    "DeclaracionJurada",
    "Escribano",
    "HistorialEstado",
    "PasswordResetToken",
    "Permission",
    "Persona",
    "RecoveryCode",
    "RegistroNotarial",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
    "UserSession",
    "Vencimiento",
    "Vigencia",
]
