# Documento de Ingeniería de Software — Módulo 2
## Autenticación, Control de Acceso y Gestión de Identidades (IAM & RBAC)
**Suite Integral Caja Notarial de San Juan**  
**Versión:** 1.0.0 | **Estado:** Especificación Técnica Detallada  
**Requerimientos del Pliego:** `SEC-01`, `SEC-02`, `SEC-03`, `SEC-04`, `SEC-05`, `USR-01`, `USR-02`, `USR-03`, `USR-04`  
**Stack de Referencia:** Python 3.12+ | FastAPI | PostgreSQL 16+ | SQLAlchemy 2.0 (Async) | Pydantic v2 | JWT | Argon2id / Bcrypt | PyOTP (2FA TOTP) | React + TypeScript

> **Implementación (Fase 1).** Lo construido sigue este documento con estas diferencias, que
> prevalecen sobre el texto de abajo (el playbook `AGENTS.md` manda):
>
> - **Access token en cookie HttpOnly** (`sn_access`, path `/api`, SameSite=Lax), no en
>   `Authorization: Bearer`: el plan pide sesión en cookie. Defensa CSRF por cabecera
>   `X-Requested-With` y verificación de `Origin`.
> - **Permisos leídos de la base en cada request**, no desde claims del JWT: un logout, una
>   suspensión o un cambio de rol surten efecto en la request siguiente.
> - **Login en dos pasos con 2FA:** `POST /auth/login` y luego `POST /auth/login/mfa` (TOTP o
>   código de recuperación), en lugar de enviar el TOTP junto con la contraseña. 2FA obligatorio
>   también para `ROLE_AUDITOR` (lee auditoría y reportes financieros).
> - **Mensajes de error genéricos** también ante cuenta bloqueada o suspendida (anti-enumeración);
>   el bloqueo es de 5 intentos por 15 minutos, como dice §10.
> - **Datos:** semilla TOTP cifrada con AES-GCM (`totp_secret_encrypted`), tabla
>   `security_recovery_codes` (HMAC-SHA256 con clave del servidor), columnas `old_value` /
>   `new_value` en `audit_security_logs`, IP como `INET`, CUIT de 11 dígitos sin guiones.
>   Las FK usan `ON DELETE RESTRICT`: los usuarios no se borran.
> - **Roles de base separados:** las migraciones corren con `suite_owner`; la aplicación con
>   `suite_app`, que no puede modificar ni borrar filas de auditoría.
> - **Rutas:** `/api/v1/auth/*`, `/api/v1/users`, `/api/v1/roles`, `/api/v1/audit/security-logs`.
>   El enlace de recuperación es `PUBLIC_WEB_URL/restablecer-clave#token=...`.
> - La matriz rol → permisos (§2) se implementó como propuesta técnica en
>   `backend/app/modules/iam/catalog.py`, marcada `TODO(negocio)` para validar con la Caja.

---

### 1. Propósito, Alcance y Mitigación de Defectos Críticos

El **Módulo 2 (IAM & RBAC)** constituye el perímetro de seguridad e identidad de toda la suite. Define la arquitectura de autenticación unificada para usuarios administrativos internos, tesorería, fiscalización, escribanos matriculados y consultores externos.

#### 1.1 Mitigación Directa de Hallazgos Previos
1. **Emisión de enlaces bajo dominio público (`SEC-04` / `USR-03`):** Se erradica el fallo observado en auditorías previas donde las solicitudes de recuperación emitían enlaces erróneos a servidores locales (`localhost:8080`). En la nueva arquitectura, todo enlace de notificación se construye a partir de la variable tipada de entorno `PUBLIC_WEB_URL`. El token emitido es de un solo uso, generado con entropía criptográfica (32 bytes urlsafe) y resguardado en base de datos mediante su hash SHA-256 con expiración estricta de 30 minutos.
2. **Prevención de Enumeración de Cuentas (`SEC-04`):** El endpoint de solicitud de recuperación responde un mensaje uniforme ("Si la cuenta proporcionada se encuentra registrada y activa, se enviará una comunicación con los pasos a seguir") tanto si el identificador existe como si no existe, impidiendo sondeos de usuarios.
3. **Control de Acceso Estricto en Servidor (`SEC-01`):** Se prohíbe de forma taxativa considerar el ocultamiento visual de componentes en React como mecanismo de seguridad. Cada endpoint de la API REST valida en el backend los alcances y permisos del usuario mediante inyectores de dependencia declarativos (`Depends(require_permissions(...))`).
4. **Manejo Seguro de Sesiones y Protección contra Fugas (`SEC-05`):** Implementación de tokens JWT de corta duración (15 a 30 minutos) transmitidos en cabecera `Authorization: Bearer`, combinados con Refresh Tokens rotativos almacenados exclusivamente en cookies seguras con directivas `HttpOnly`, `Secure`, `SameSite=Lax`.
5. **Autenticación Multifactorial (MFA / 2FA - `USR-04`):** Soporte nativo para Time-based One-Time Password (TOTP, RFC 6238) mediante aplicaciones autenticadoras estándar (Google Authenticator, Microsoft Authenticator), obligatorio para roles de alta jerarquía (`ADMIN`, `TESORERIA`, `CAJA`).
6. **Auditoría Inmutable de Accesos y Cambios de Credenciales (`SEC-03`):** Registro estructurado de cada evento de autenticación (éxitos, fallos, bloqueos por reiteración, cambios de clave y revocaciones de permisos), registrando dirección IP, User-Agent y marca temporal en UTC.

---

### 2. Matriz de Roles y Catálogo Granular de Permisos (RBAC)

El sistema implementa un modelo de Control de Acceso Basado en Roles (RBAC) desacoplado mediante permisos atómicos. Los roles agrupan conjuntos de permisos predeterminados, pero la autorización en la API se comprueba siempre contra el permiso específico de la acción.

#### 2.1 Perfiles y Roles Candidatos (`SEC-02`)

| Código de Rol | Denominación Funcional | Alcance Operativo |
| :--- | :--- | :--- |
| `ROLE_ADMIN` | Administrador del Sistema | Gestión técnica integral, usuarios, roles, parámetros del sistema, auditoría forense. |
| `ROLE_CAJA` | Administración de Caja | Padrón de escribanos, recepción de DDJJ, consulta de boletas, carga de novedades y parámetros operativos. |
| `ROLE_TESORERIA` | Tesorería y Cobranzas | Verificación y conciliación de comprobantes de pago, liquidación de haberes, reportes contables y financieros. |
| `ROLE_ESCRIBANO` | Escribano / Afiliado | Portal de autogestión: carga de DDJJ mensuales, descarga de boletas, adjunción de comprobantes, consulta de préstamos y trámites personales. |
| `ROLE_AUDITOR` | Auditoría y Fiscalización | Consulta de sólo lectura de registros históricos, DDJJ, contabilidad, parámetros y logs de auditoría sin capacidad de modificación. |
| `ROLE_PUBLICO` | Usuario Público | Acceso a contenidos institucionales, noticias y documentos públicos validados a través del CMS institucional. |

#### 2.2 Catálogo Granular de Permisos Atómicos

```text
# Usuarios y Roles
users:read              # Consultar listados y detalles de usuarios
users:write             # Crear y editar usuarios
users:suspend           # Suspender / reactivar cuentas de usuarios (USR-02)
roles:manage            # Asignar roles y modificar permisos

# Padrón de Escribanos y Registros
escribanos:read         # Consultar afiliados y registros notariales (DIR-01)
escribanos:write        # Alta y modificación de escribanos y matrículas (DIR-02)
escribanos:status       # Modificar estado de matrícula (activo, suspendido, cesante)

# Declaraciones Juradas y Boletas
ddjj:read_own           # Consultar declaraciones juradas propias (portal escribano)
ddjj:create_own         # Presentar nueva declaración jurada mensual (DDJJ-01)
ddjj:read_all           # Consultar DDJJ de cualquier escribano (Caja/Tesorería)
ddjj:approve            # Confirmar y asentar liquidación de protocolos

# Boletas y Comprobantes
boletas:read_own        # Descargar boleta de pago propia
boletas:read_all        # Consultar y emitir boletas globales
comprobantes:upload     # Adjuntar comprobante bancario a boleta emitida (DDJJ-04)
comprobantes:verify     # Revisar, conciliar y aprobar/rechazar comprobante (DDJJ-06, Tesorería)

# Parámetros Previsionales
parameters:read         # Consultar catálogo de alícuotas y aportes vigentes
parameters:write        # Crear o actualizar parámetros y vigencias (PAR-01, PAR-04)

# Reportes y Auditoría
reports:financial       # Visualizar y exportar reportes de recaudación y deuda (REP-01, REP-02)
audit:read              # Visualizar registros inmutables de auditoría (SEC-03)

# CMS y Sitio Público
cms:publish             # Redactar y publicar noticias, páginas y estados contables (WEB-01, WEB-02)
```

---

### 3. Modelo de Datos Relacional (PostgreSQL & SQLAlchemy 2.0)

#### 3.1 Script DDL de Base de Datos (PostgreSQL)

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Tabla de Roles
CREATE TABLE IF NOT EXISTS security_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Tabla de Permisos Atómicos
CREATE TABLE IF NOT EXISTS security_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(100) UNIQUE NOT NULL,
    module VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

-- Tabla Puente Roles - Permisos
CREATE TABLE IF NOT EXISTS security_role_permissions (
    role_id UUID NOT NULL REFERENCES security_roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES security_permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

-- Tabla Central de Usuarios
CREATE TABLE IF NOT EXISTS security_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    cuit VARCHAR(13) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(200) NOT NULL,
    phone_number VARCHAR(50),
    
    -- Control de Estado y Acceso (USR-02)
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    suspension_reason TEXT,
    suspended_at TIMESTAMPTZ,
    suspended_by_user_id UUID REFERENCES security_users(id),
    
    -- Mecanismo de Segundo Factor (2FA TOTP - USR-04)
    totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    totp_secret VARCHAR(64),
    
    -- Control de Intentos Fallidos
    failed_login_attempts INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    last_login_ip VARCHAR(45),
    
    -- Trazabilidad y Auditoría (AuditMixin)
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    created_by_user_id UUID REFERENCES security_users(id)
);

CREATE INDEX idx_users_email ON security_users(email);
CREATE INDEX idx_users_cuit ON security_users(cuit);

-- Tabla Puente Usuarios - Roles
CREATE TABLE IF NOT EXISTS security_user_roles (
    user_id UUID NOT NULL REFERENCES security_users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES security_roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    assigned_by_user_id UUID REFERENCES security_users(id),
    PRIMARY KEY (user_id, role_id)
);

-- Tabla de Tokens de Restablecimiento de Credenciales (SEC-04)
CREATE TABLE IF NOT EXISTS security_password_reset_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES security_users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    created_by_ip VARCHAR(45) NOT NULL
);

CREATE INDEX idx_reset_token_hash ON security_password_reset_tokens(token_hash);
CREATE INDEX idx_reset_token_user_expires ON security_password_reset_tokens(user_id, expires_at);

-- Tabla de Sesiones y Refresh Tokens Rotativos (SEC-05)
CREATE TABLE IF NOT EXISTS security_user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES security_users(id) ON DELETE CASCADE,
    refresh_token_hash VARCHAR(64) UNIQUE NOT NULL,
    session_family_id UUID NOT NULL,
    ip_address VARCHAR(45) NOT NULL,
    user_agent TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX idx_sessions_user_family ON security_user_sessions(user_id, session_family_id);

-- Tabla Central de Auditoría Forense e Inmutable (SEC-03)
CREATE TABLE IF NOT EXISTS audit_security_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    event_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'INFO',
    actor_user_id UUID REFERENCES security_users(id),
    target_user_id UUID REFERENCES security_users(id),
    ip_address VARCHAR(45) NOT NULL,
    user_agent TEXT,
    correlation_id VARCHAR(100),
    details JSONB
);

CREATE INDEX idx_audit_event_timestamp ON audit_security_logs(event_timestamp);
CREATE INDEX idx_audit_actor ON audit_security_logs(actor_user_id);
CREATE INDEX idx_audit_event_type ON audit_security_logs(event_type);
```

---

### 4. Modelos Declarativos en Python (SQLAlchemy 2.0 Async)

#### 4.1 Definición de Entidades (`backend/app/models/security.py`)

```python
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Any
from sqlalchemy import String, Boolean, Integer, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, AuditMixin, utc_now

class Role(Base):
    __tablename__ = "security_roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    users: Mapped[List["User"]] = relationship(
        "User", secondary="security_user_roles", back_populates="roles"
    )
    permissions: Mapped[List["Permission"]] = relationship(
        "Permission", secondary="security_role_permissions", back_populates="roles", lazy="selectin"
    )

class Permission(Base):
    __tablename__ = "security_permissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    roles: Mapped[List[Role]] = relationship(
        Role, secondary="security_role_permissions", back_populates="permissions"
    )

class User(Base, AuditMixin):
    __tablename__ = "security_users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    cuit: Mapped[str] = mapped_column(String(13), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Estado y suspensión (USR-02)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suspension_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suspended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )

    # Segundo factor de autenticación (USR-04)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    totp_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Control de intentos fallidos
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    roles: Mapped[List[Role]] = relationship(
        Role, secondary="security_user_roles", back_populates="users", lazy="selectin"
    )

class PasswordResetToken(Base):
    __tablename__ = "security_password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_by_ip: Mapped[str] = mapped_column(String(45), nullable=False)

class AuditSecurityLog(Base):
    __tablename__ = "audit_security_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="INFO", nullable=False)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True, index=True
    )
    target_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_users.id"), nullable=True
    )
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
```

---

### 5. Utilidades Criptográficas y de Seguridad (`backend/app/core/security.py`)

```python
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from passlib.context import CryptContext
from jose import jwt
import pyotp
from app.core.config import settings

pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

def generate_secure_url_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)

def create_access_token(subject: str, permissions: list[str], roles: list[str], expires_delta: Optional[timedelta] = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode = {
        "sub": str(subject),
        "iat": now,
        "exp": expire,
        "nbf": now,
        "type": "access",
        "roles": roles,
        "permissions": permissions,
    }
    return jwt.encode(to_encode, settings.AUTH_SECRET_KEY, algorithm=settings.ALGORITHM)

def generate_totp_secret() -> str:
    return pyotp.random_base32()

def verify_totp_code(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)

def get_totp_uri(secret: str, user_email: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=user_email, issuer_name="Caja Notarial de San Juan")
```

---

### 6. Contratos de Datos Pydantic v2 (`backend/app/schemas/security.py`)

```python
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator
import re

class LoginRequest(BaseModel):
    username: str = Field(..., description="Email institucional o CUIT (sin guiones o con formato)")
    password: str = Field(..., min_length=8)
    totp_code: Optional[str] = Field(None, min_length=6, max_length=6, description="Código de 6 dígitos si tiene 2FA")

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user_id: uuid.UUID
    full_name: str
    roles: List[str]
    permissions: List[str]
    totp_required: bool = False

class PasswordResetRequest(BaseModel):
    identifier: str = Field(..., description="Email o CUIT del usuario solicitante")

class PasswordResetConfirm(BaseModel):
    token: str = Field(..., description="Token recibido vía correo electrónico")
    new_password: str = Field(..., min_length=10, description="Nueva contraseña segura")

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("La contraseña debe incluir al menos una letra mayúscula.")
        if not re.search(r"[a-z]", v):
            raise ValueError("La contraseña debe incluir al menos una letra minúscula.")
        if not re.search(r"[0-9]", v):
            raise ValueError("La contraseña debe incluir al menos un número.")
        if not re.search(r"[\W_]", v):
            raise ValueError("La contraseña debe incluir al menos un carácter especial.")
        return v

class TOTPSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str

class TOTPVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)

class UserStatusUpdateRequest(BaseModel):
    is_active: bool
    reason: str = Field(..., min_length=5, description="Motivo obligatorio del cambio de estado (USR-02)")
```

---

### 7. Endpoints de la API REST e Inyectores de Dependencia (`backend/app/api/v1/endpoints/auth.py`)

#### 7.1 Inyector de Dependencias de Autorización (`backend/app/api/deps.py`)

```python
import uuid
from typing import List, Callable
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db_session
from app.models.security import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db_session)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales de acceso.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = uuid.UUID(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    stmt = select(User).where(User.id == user_id, User.is_active == True)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inexistente o inactivo.")
    return user

def require_permissions(*required_permissions: str) -> Callable:
    """Inyector de dependencia para validación estricta de permisos en servidor (SEC-01)."""
    async def permission_checker(
        token: str = Depends(oauth2_scheme),
        current_user: User = Depends(get_current_user)
    ):
        try:
            payload = jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_permissions: List[str] = payload.get("permissions", [])
            for perm in required_permissions:
                if perm not in user_permissions:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Permiso insuficiente en servidor. Se requiere '{perm}' (SEC-01)."
                    )
        except JWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token no válido.")
        return current_user
    return permission_checker
```

#### 7.2 Controlador de Autenticación y Restablecimiento

```python
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db_session
from app.core.security import (
    verify_password, get_password_hash, create_access_token,
    generate_secure_url_token, hash_token, verify_totp_code
)
from app.models.security import User, PasswordResetToken, AuditSecurityLog
from app.schemas.security import (
    LoginRequest, TokenResponse, PasswordResetRequest, PasswordResetConfirm
)

router = APIRouter(prefix="/auth", tags=["Autenticación y Seguridad"])

@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session)
):
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("User-Agent", "unknown")
    correlation_id = getattr(request.state, "correlation_id", None)

    clean_identifier = req.username.strip().replace("-", "")
    stmt = select(User).where(
        (User.email == req.username.strip().lower()) | (User.cuit == clean_identifier)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        audit = AuditSecurityLog(
            event_type="LOGIN_FAILED_NOT_FOUND",
            severity="WARNING",
            ip_address=ip_address,
            user_agent=user_agent,
            correlation_id=correlation_id,
            details={"identifier": req.username}
        )
        db.add(audit)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas.")

    now = datetime.now(timezone.utc)
    if user.locked_until and user.locked_until > now:
        remaining_minutes = int((user.locked_until - now).total_seconds() / 60)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cuenta bloqueada temporalmente por intentos fallidos. Reintente en {remaining_minutes} minutos."
        )

    if not verify_password(req.password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= 5:
            user.locked_until = now + timedelta(minutes=15)
        
        audit = AuditSecurityLog(
            event_type="LOGIN_FAILED_BAD_PASSWORD",
            severity="WARNING",
            actor_user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            correlation_id=correlation_id,
            details={"failed_attempts": user.failed_login_attempts}
        )
        db.add(audit)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas.")

    if user.totp_enabled:
        if not req.totp_code or not verify_totp_code(user.totp_secret, req.totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Código de autenticación 2FA requerido o inválido."
            )

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = ip_address

    role_codes = [role.code for role in user.roles if role.is_active]
    permission_set = set()
    for role in user.roles:
        if role.is_active:
            for perm in role.permissions:
                permission_set.add(perm.code)
    permissions_list = list(permission_set)

    access_token = create_access_token(
        subject=str(user.id),
        permissions=permissions_list,
        roles=role_codes
    )

    audit = AuditSecurityLog(
        event_type="LOGIN_SUCCESS",
        severity="INFO",
        actor_user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
        details={"roles": role_codes}
    )
    db.add(audit)
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        expires_in_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=user.id,
        full_name=user.full_name,
        roles=role_codes,
        permissions=permissions_list,
        totp_required=user.totp_enabled
    )

@router.post("/password-reset/request", status_code=status.HTTP_200_OK)
async def request_password_reset(
    req: PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Solicitud de recuperación de credenciales (SEC-04).
    Construye enlace seguro bajo el dominio configurado e invalida su uso tras el consumo.
    Previene enumeración devolviendo idéntica respuesta genérica.
    """
    ip_address = request.client.host if request.client else "unknown"
    clean_identifier = req.identifier.strip().replace("-", "")

    stmt = select(User).where(
        (User.email == req.identifier.strip().lower()) | (User.cuit == clean_identifier)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user and user.is_active:
        raw_token = generate_secure_url_token(32)
        token_hashed = hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)

        reset_entry = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hashed,
            expires_at=expires_at,
            created_by_ip=ip_address
        )
        db.add(reset_entry)

        audit = AuditSecurityLog(
            event_type="PASSWORD_RESET_REQUESTED",
            severity="INFO",
            target_user_id=user.id,
            ip_address=ip_address,
            correlation_id=getattr(request.state, "correlation_id", None),
            details={"expires_at": expires_at.isoformat(), "public_domain": str(settings.PUBLIC_WEB_URL)}
        )
        db.add(audit)
        await db.commit()

    return {
        "status": "success",
        "message": "Si la cuenta proporcionada se encuentra registrada y activa, se ha enviado un correo con las instrucciones de recuperación."
    }

@router.post("/password-reset/confirm", status_code=status.HTTP_200_OK)
async def confirm_password_reset(
    req: PasswordResetConfirm,
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    ip_address = request.client.host if request.client else "unknown"
    token_hashed = hash_token(req.token)
    now = datetime.now(timezone.utc)

    stmt = select(PasswordResetToken).where(
        PasswordResetToken.token_hash == token_hashed,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > now
    )
    result = await db.execute(stmt)
    token_record = result.scalar_one_or_none()

    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El token de recuperación es inválido, ha expirado o ya ha sido utilizado (SEC-04)."
        )

    stmt_user = select(User).where(User.id == token_record.user_id)
    res_user = await db.execute(stmt_user)
    user = res_user.scalar_one()

    user.hashed_password = get_password_hash(req.new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    token_record.used_at = now

    audit = AuditSecurityLog(
        event_type="PASSWORD_RESET_COMPLETED",
        severity="INFO",
        actor_user_id=user.id,
        target_user_id=user.id,
        ip_address=ip_address,
        correlation_id=getattr(request.state, "correlation_id", None),
        details={"status": "password_updated_successfully"}
    )
    db.add(audit)
    await db.commit()

    return {
        "status": "success",
        "message": "La contraseña ha sido actualizada exitosamente. Ya puede iniciar sesión con sus nuevas credenciales."
    }
```

---

### 8. Frontend: Componente de Protección de Rutas (`frontend/src/components/ProtectedRoute.tsx`)

```tsx
import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

interface ProtectedRouteProps {
  requiredPermissions?: string[];
  requiredRoles?: string[];
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  requiredPermissions = [],
  requiredRoles = []
}) => {
  const { user, isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <div className="flex h-screen items-center justify-center">Verificando sesión...</div>;
  }

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" replace />;
  }

  if (requiredRoles.length > 0) {
    const hasRole = requiredRoles.some(role => user.roles.includes(role));
    if (!hasRole) {
      return <Navigate to="/unauthorized" replace />;
    }
  }

  if (requiredPermissions.length > 0) {
    const hasPermission = requiredPermissions.every(perm => user.permissions.includes(perm));
    if (!hasPermission) {
      return <Navigate to="/unauthorized" replace />;
    }
  }

  return <Outlet />;
};
```

---

### 9. Suite de Pruebas Automatizadas (`backend/tests/test_iam_security.py`)

```python
import pytest
from httpx import AsyncClient
from datetime import datetime, timedelta, timezone
from app.core.config import settings
from app.core.security import get_password_hash, create_access_token

@pytest.mark.asyncio
async def test_server_enforces_permission_sec_01(client: AsyncClient, test_user):
    token_limited = create_access_token(
        subject=str(test_user.id),
        permissions=["parameters:read"],
        roles=["ROLE_AUDITOR"]
    )
    response = await client.post(
        f"{settings.API_V1_STR}/parameters/",
        json={"name": "Aporte Previsional Base", "value": 15000.00},
        headers={"Authorization": f"Bearer {token_limited}"}
    )
    assert response.status_code == 403
    assert "Permiso insuficiente en servidor" in response.json()["detail"]

@pytest.mark.asyncio
async def test_password_reset_leak_prevention_sec_04(client: AsyncClient):
    response = await client.post(
        f"{settings.API_V1_STR}/auth/password-reset/request",
        json={"identifier": "usuario_inexistente_999@cajanotarial.org.ar"}
    )
    assert response.status_code == 200
    assert "Si la cuenta proporcionada se encuentra registrada" in response.json()["message"]

@pytest.mark.asyncio
async def test_password_reset_single_use_token_sec_04(client: AsyncClient, db_session, test_user):
    raw_token = "token_de_prueba_seguro_12345"
    from app.core.security import hash_token
    from app.models.security import PasswordResetToken

    token_obj = PasswordResetToken(
        user_id=test_user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        created_by_ip="127.0.0.1"
    )
    db_session.add(token_obj)
    await db_session.commit()

    res1 = await client.post(
        f"{settings.API_V1_STR}/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": "NewSecretPassword123!"}
    )
    assert res1.status_code == 200

    res2 = await client.post(
        f"{settings.API_V1_STR}/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": "AnotherPassword123!"}
    )
    assert res2.status_code == 400
    assert "inválido, ha expirado o ya ha sido utilizado" in res2.json()["detail"]
```

---

### 10. Criterios de Aceptación del Módulo 2

1. **Cumplimiento SEC-01:** La API rechaza con `HTTP 403 Forbidden` cualquier invocación directa a endpoints no autorizados sin importar los permisos que simule tener el cliente web.
2. **Cumplimiento SEC-04:** Todo correo de restablecimiento emite un enlace con el dominio real configurado en `PUBLIC_WEB_URL`. El token queda invalidado tras su primer uso o vencido a los 30 minutos.
3. **Protección contra Enumeración:** Las respuestas a solicitudes de restablecimiento de contraseña son homogéneas.
4. **Protección contra Intentos Fallidos:** Cinco intentos consecutivos fallidos de autenticación bloquean temporalmente la cuenta por 15 minutos, registrándose en `audit_security_logs`.
5. **Autenticación en Servidor para 2FA (`USR-04`):** Usuarios con doble factor activado no pueden obtener tokens válidos sin suministrar el código TOTP sincronizado.
