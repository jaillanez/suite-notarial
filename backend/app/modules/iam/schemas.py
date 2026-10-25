"""Contratos de entrada y salida del módulo IAM."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.common.cuit import InvalidCuitError, normalize_cuit

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]
PasswordInput = Annotated[str, StringConstraints(min_length=1, max_length=256)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]
OtpInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=6, max_length=12)]


class LoginRequest(BaseModel):
    identifier: Identifier = Field(description="Email o CUIT (con o sin guiones)")
    password: PasswordInput


class MfaLoginRequest(BaseModel):
    code: OtpInput = Field(description="Código TOTP de 6 dígitos o código de recuperación")


class SessionUser(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    cuit: str
    roles: list[str]
    permissions: list[str]
    mfa_enabled: bool
    mfa_required: bool
    mfa_verified: bool


class LoginResponse(BaseModel):
    status: Literal["authenticated", "mfa_required"]
    user: SessionUser | None = None


class MessageResponse(BaseModel):
    message: str


class PasswordResetRequest(BaseModel):
    identifier: Identifier


class PasswordResetConfirm(BaseModel):
    token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=20, max_length=200)]
    new_password: PasswordInput


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class MfaCodeRequest(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$")]


class MfaDisableRequest(MfaCodeRequest):
    password: PasswordInput


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    description: str | None
    mfa_required: bool
    permissions: list[str]


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    cuit: str
    phone_number: str | None
    roles: list[str]
    is_active: bool
    suspension_reason: str | None
    suspended_at: datetime | None
    mfa_enabled: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    full_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)
    ]
    cuit: str
    phone_number: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = (
        None
    )
    roles: list[str] = Field(min_length=1)

    @field_validator("cuit")
    @classmethod
    def _valid_cuit(cls, value: str) -> str:
        try:
            return normalize_cuit(value)
        except InvalidCuitError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str) -> str:
        return value.lower()


class UserStatusUpdate(BaseModel):
    is_active: bool
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]


class UserRolesUpdate(BaseModel):
    roles: list[str]


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_timestamp: datetime
    event_type: str
    severity: str
    actor_user_id: uuid.UUID | None
    actor_email: str | None = None
    target_user_id: uuid.UUID | None
    target_email: str | None = None
    ip_address: str | None
    correlation_id: str | None
    old_value: dict[str, object] | None
    new_value: dict[str, object] | None
    details: dict[str, object] | None

    @field_validator("ip_address", mode="before")
    @classmethod
    def _ip_to_str(cls, value: object) -> str | None:
        return None if value is None else str(value)
