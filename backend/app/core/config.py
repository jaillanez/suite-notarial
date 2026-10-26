"""Configuración tipada de la aplicación, leída de variables de entorno / `.env`."""

import base64
import binascii
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


_PRIVATE_HOSTS = ("localhost", "127.", "10.", "192.168.", "0.0.0.0", "[::1]")  # noqa: S104


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    # Rol de la aplicación (sin privilegios de dueño). Ver scripts/bootstrap_db.sh.
    DATABASE_URL: PostgresDsn
    # Rol dueño del esquema, solo para migraciones. Si falta, se usa DATABASE_URL.
    MIGRATIONS_DATABASE_URL: PostgresDsn | None = None
    PUBLIC_WEB_URL: HttpUrl
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    JWT_SECRET: SecretStr
    JWT_ACCESS_TTL_MIN: Annotated[int, Field(gt=0)] = 15
    JWT_REFRESH_TTL_DAYS: Annotated[int, Field(gt=0)] = 7
    COOKIE_SECURE: bool = True
    COOKIE_DOMAIN: str | None = None

    # Clave AES-256 en base64 (32 bytes) para cifrar secretos en reposo (p. ej. semillas TOTP).
    DATA_ENCRYPTION_KEY: SecretStr
    LOGIN_MAX_ATTEMPTS: Annotated[int, Field(gt=0)] = 5
    LOGIN_LOCK_MINUTES: Annotated[int, Field(gt=0)] = 15
    MFA_PENDING_TTL_MIN: Annotated[int, Field(gt=0)] = 5
    TOTP_ISSUER: str = "Caja Notarial de San Juan"
    # 2FA obligatorio para los roles que lo exigen. Solo se puede apagar en development/test,
    # para no tener que reactivarlo después de cada `make reset-dev`.
    MFA_ENFORCED: bool = True

    SMTP_HOST: str = "localhost"
    SMTP_PORT: Annotated[int, Field(gt=0, lt=65536)] = 1025
    # "none" solo se admite en development/test (Mailpit local); fuera de eso, TLS obligatorio.
    SMTP_SECURITY: Literal["none", "starttls", "tls"] = "none"
    SMTP_USER: str | None = None
    SMTP_PASSWORD: SecretStr | None = None
    MAIL_FROM: str = "no-responder@cajanotarial.local"
    PASSWORD_RESET_TTL_MIN: Annotated[int, Field(gt=0)] = 30

    UPLOAD_DIR: Path = Path("var/uploads")
    MAX_UPLOAD_MB: Annotated[int, Field(gt=0)] = 10
    # Documentos oficiales del sitio (balances, memorias): suelen ser más pesados.
    CMS_MAX_DOC_MB: Annotated[int, Field(gt=0)] = 25

    # IA asistencial (Fase 9): OCR local con Tesseract, sin servicios externos.
    IA_TESSERACT_CMD: str = "tesseract"
    # Idiomas preferidos; se usan los instalados ("spa" viene en `brew install tesseract-lang`).
    IA_OCR_IDIOMAS: str = "spa+eng"
    IA_OCR_TIMEOUT_S: Annotated[int, Field(gt=0, le=300)] = 30
    IA_OCR_CONCURRENCIA: Annotated[int, Field(gt=0, le=16)] = 2

    # Migración (Fase 10): simulacros cuadrados exigidos antes de la carga definitiva
    # (módulo 11: tres simulacros completos).
    MIGRACION_SIMULACROS_MINIMOS: Annotated[int, Field(ge=1, le=20)] = 3

    LOG_LEVEL: str = "INFO"

    # Datos de la Caja y de la cuenta recaudadora que se imprimen en la boleta. Los valores
    # reales van solo en el `.env` del entorno (nunca en el repositorio).
    CAJA_NOMBRE: str = "Caja Notarial de San Juan"
    CAJA_CUIT: str | None = None
    CAJA_DOMICILIO: str | None = None
    CAJA_CONTACTO: str | None = None
    BANCO_NOMBRE: str | None = None
    BANCO_CUENTA: str | None = None
    BANCO_CBU: str | None = None
    BANCO_ALIAS: str | None = None

    # Solo desarrollo: contraseña de los usuarios de demostración (make seed-dev).
    DEV_SEED_PASSWORD: SecretStr | None = None

    @field_validator("JWT_SECRET")
    @classmethod
    def _jwt_secret_length(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET debe tener al menos 32 caracteres")
        return value

    @field_validator("DATA_ENCRYPTION_KEY")
    @classmethod
    def _encryption_key_size(cls, value: SecretStr) -> SecretStr:
        try:
            raw = base64.b64decode(value.get_secret_value(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("DATA_ENCRYPTION_KEY debe estar en base64") from exc
        if len(raw) != 32:
            raise ValueError("DATA_ENCRYPTION_KEY debe decodificar a 32 bytes (AES-256)")
        return value

    @field_validator("PUBLIC_WEB_URL")
    @classmethod
    def _public_url_not_private(cls, value: HttpUrl, info: object) -> HttpUrl:
        # SEC-04: fuera de desarrollo/test los enlaces públicos nunca apuntan a hosts privados.
        data = getattr(info, "data", {})
        env = data.get("ENVIRONMENT", Environment.DEVELOPMENT)
        host = urlparse(str(value)).hostname or ""
        if env in (Environment.STAGING, Environment.PRODUCTION) and host.startswith(_PRIVATE_HOSTS):
            raise ValueError("PUBLIC_WEB_URL no puede apuntar a un host privado en este entorno")
        return value

    @model_validator(mode="after")
    def _smtp_tls_outside_dev(self) -> "Settings":
        if (
            self.ENVIRONMENT in (Environment.STAGING, Environment.PRODUCTION)
            and self.SMTP_SECURITY == "none"
        ):
            raise ValueError("SMTP_SECURITY debe ser 'starttls' o 'tls' fuera de desarrollo")
        if not self.MFA_ENFORCED and self.ENVIRONMENT not in (
            Environment.DEVELOPMENT,
            Environment.TEST,
        ):
            raise ValueError("MFA_ENFORCED=false solo se admite en development o test")
        if self.SMTP_USER and self.SMTP_SECURITY == "none":
            raise ValueError(
                "No se envían credenciales SMTP sin TLS: usá SMTP_SECURITY starttls o tls"
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT is Environment.PRODUCTION

    @property
    def migrations_database_url(self) -> str:
        return str(self.MIGRATIONS_DATABASE_URL or self.DATABASE_URL)

    @property
    def public_web_base(self) -> str:
        """`PUBLIC_WEB_URL` sin barra final, para construir enlaces (SEC-04)."""
        return str(self.PUBLIC_WEB_URL).rstrip("/")

    @property
    def data_encryption_key(self) -> bytes:
        return base64.b64decode(self.DATA_ENCRYPTION_KEY.get_secret_value())

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
