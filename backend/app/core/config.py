"""Configuración tipada de la aplicación, leída de variables de entorno / `.env`."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr, field_validator
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
    DATABASE_URL: PostgresDsn
    PUBLIC_WEB_URL: HttpUrl
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    JWT_SECRET: SecretStr
    JWT_ACCESS_TTL_MIN: Annotated[int, Field(gt=0)] = 15
    JWT_REFRESH_TTL_DAYS: Annotated[int, Field(gt=0)] = 7
    COOKIE_SECURE: bool = True
    COOKIE_DOMAIN: str | None = None

    SMTP_HOST: str = "localhost"
    SMTP_PORT: Annotated[int, Field(gt=0, lt=65536)] = 1025
    MAIL_FROM: str = "no-responder@cajanotarial.local"
    PASSWORD_RESET_TTL_MIN: Annotated[int, Field(gt=0)] = 30

    UPLOAD_DIR: Path = Path("var/uploads")
    MAX_UPLOAD_MB: Annotated[int, Field(gt=0)] = 10

    LOG_LEVEL: str = "INFO"

    @field_validator("JWT_SECRET")
    @classmethod
    def _jwt_secret_length(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET debe tener al menos 32 caracteres")
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

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT is Environment.PRODUCTION

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
