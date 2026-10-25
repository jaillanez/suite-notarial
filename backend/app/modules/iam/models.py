"""Modelos de identidad, roles, permisos y sesiones (Módulo 2)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Permission(UUIDMixin, Base):
    __tablename__ = "security_permissions"

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RolePermission(Base):
    __tablename__ = "security_role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_roles.id", ondelete="RESTRICT"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("security_permissions.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class Role(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "security_roles"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    mfa_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    permissions: Mapped[list[Permission]] = relationship(
        secondary="security_role_permissions", lazy="selectin", order_by=Permission.code
    )


class UserRole(Base):
    __tablename__ = "security_user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id", ondelete="RESTRICT"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_roles.id", ondelete="RESTRICT"), primary_key=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )


class User(UUIDMixin, TimestampMixin, Base):
    """Usuario del sistema. Nunca se borra: se suspende (regla INM)."""

    __tablename__ = "security_users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("cuit ~ '^[0-9]{11}$'", name="cuit_digits"),
        CheckConstraint("failed_login_attempts >= 0", name="failed_attempts_non_negative"),
    )

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    cuit: Mapped[str] = mapped_column(String(11), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )

    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Semilla TOTP cifrada con AES-GCM (ver app.core.crypto); nunca en claro.
    totp_secret_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Último paso de 30 s aceptado: impide reutilizar un mismo código (anti-replay).
    totp_last_used_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )

    roles: Mapped[list[Role]] = relationship(
        secondary="security_user_roles",
        primaryjoin="User.id == UserRole.user_id",
        secondaryjoin="Role.id == UserRole.role_id",
        lazy="selectin",
        order_by=Role.code,
    )

    @property
    def active_roles(self) -> list[Role]:
        return [role for role in self.roles if role.is_active]

    @property
    def role_codes(self) -> list[str]:
        return [role.code for role in self.active_roles]

    @property
    def permission_codes(self) -> frozenset[str]:
        return frozenset(p.code for role in self.active_roles for p in role.permissions)

    @property
    def mfa_required(self) -> bool:
        return any(role.mfa_required for role in self.active_roles)


class PasswordResetToken(UUIDMixin, Base):
    __tablename__ = "security_password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("security_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by_ip: Mapped[str | None] = mapped_column(INET, nullable=True)


class UserSession(UUIDMixin, Base):
    """Sesión con refresh token rotativo. Cada rotación crea una fila nueva de la misma familia."""

    __tablename__ = "security_user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("security_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    session_family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    mfa_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RecoveryCode(UUIDMixin, Base):
    """Código de recuperación de 2FA, de un solo uso, guardado como HMAC-SHA256."""

    __tablename__ = "security_recovery_codes"
    __table_args__ = (UniqueConstraint("user_id", "code_hash"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("security_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
