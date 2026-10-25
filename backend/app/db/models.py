"""Registro central de modelos para Alembic.

Cada módulo que defina modelos debe importarse acá para que `--autogenerate` los detecte.
"""

from app.common.audit import AuditSecurityLog
from app.db.base import Base
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
from app.modules.parametros.models import Concepto, Vigencia

__all__ = [
    "Adscripcion",
    "AuditSecurityLog",
    "Base",
    "Circunscripcion",
    "Concepto",
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
    "Vigencia",
]
