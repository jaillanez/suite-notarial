"""Almacenamiento de comprobantes (regla MIME).

- El tipo se decide por los *magic bytes* del contenido, nunca por la extensión ni por el
  `Content-Type` que manda el navegador. Solo PDF, PNG y JPEG.
- Tamaño máximo `MAX_UPLOAD_MB`, controlado mientras se lee (no se carga un archivo enorme).
- Nombre UUID con la extensión del tipo real, bajo `UPLOAD_DIR/comprobantes/AAAA/MM/`, fuera de
  cualquier directorio servido como estático. Permisos 0600 y creación exclusiva.
- Se guarda la huella SHA-256: al servirlo se verifica que el archivo no cambió.
"""

import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import anyio
import magic
from fastapi import UploadFile

from app.core.config import Settings
from app.modules.pagos.catalog import MIME_PERMITIDOS

BACKEND_DIR = Path(__file__).resolve().parents[3]
CHUNK = 64 * 1024
SUBDIR = "comprobantes"


class ArchivoInvalidoError(ValueError):
    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


class ArchivoAlteradoError(RuntimeError):
    """El archivo guardado ya no coincide con la huella registrada."""


@dataclass(frozen=True)
class ArchivoValidado:
    contenido: bytes
    mime_type: str
    extension: str
    sha256: str
    nombre_original: str

    @property
    def tamano(self) -> int:
        return len(self.contenido)


def upload_root(settings: Settings) -> Path:
    root = settings.UPLOAD_DIR
    return (root if root.is_absolute() else BACKEND_DIR / root).resolve()


def _nombre_original(nombre: str | None) -> str:
    # Solo se conserva para mostrarlo: sin rutas ni caracteres de control.
    base = Path(nombre or "comprobante").name
    limpio = "".join(ch for ch in base if ch.isprintable()).strip()
    return (limpio or "comprobante")[:255]


async def validar(file: UploadFile, max_bytes: int) -> ArchivoValidado:
    partes: list[bytes] = []
    total = 0
    while chunk := await file.read(CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise ArchivoInvalidoError(
                f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB.", status=413
            )
        partes.append(chunk)
    contenido = b"".join(partes)
    if not contenido:
        raise ArchivoInvalidoError("El archivo está vacío.", status=422)
    mime_type = magic.from_buffer(contenido[:2048], mime=True)
    if mime_type not in MIME_PERMITIDOS:
        raise ArchivoInvalidoError(
            "Formato no admitido: el comprobante tiene que ser un PDF, PNG o JPG.", status=415
        )
    return ArchivoValidado(
        contenido=contenido,
        mime_type=mime_type,
        extension=MIME_PERMITIDOS[mime_type],
        sha256=hashlib.sha256(contenido).hexdigest(),
        nombre_original=_nombre_original(file.filename),
    )


def _escribir(destino: Path, contenido: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(contenido)


async def guardar(settings: Settings, archivo: ArchivoValidado, hoy: date) -> str:
    """Guarda el archivo y devuelve su ruta relativa a `UPLOAD_DIR` (lo que va a la base)."""
    relativa = f"{SUBDIR}/{hoy.year:04d}/{hoy.month:02d}/{uuid.uuid4().hex}{archivo.extension}"
    await anyio.to_thread.run_sync(_escribir, upload_root(settings) / relativa, archivo.contenido)
    return relativa


def _ruta(settings: Settings, relativa: str) -> Path:
    root = upload_root(settings)
    ruta = (root / relativa).resolve()
    # Defensa en profundidad: la ruta sale de la base, pero nunca se sale de UPLOAD_DIR.
    if not ruta.is_relative_to(root):
        raise ArchivoAlteradoError("Ruta de archivo fuera del almacenamiento.")
    return ruta


async def eliminar(settings: Settings, relativa: str) -> None:
    """Borra un archivo recién guardado cuyo registro no llegó a la base (no deja huérfanos)."""
    await anyio.to_thread.run_sync(lambda: _ruta(settings, relativa).unlink(missing_ok=True))


async def leer(settings: Settings, relativa: str, sha256: str) -> bytes:
    contenido = await anyio.to_thread.run_sync(_ruta(settings, relativa).read_bytes)
    if hashlib.sha256(contenido).hexdigest() != sha256:
        raise ArchivoAlteradoError("El archivo no coincide con su huella registrada.")
    return contenido
