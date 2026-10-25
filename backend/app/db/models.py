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

__all__ = [
    "AuditSecurityLog",
    "Base",
    "PasswordResetToken",
    "Permission",
    "RecoveryCode",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
    "UserSession",
]
