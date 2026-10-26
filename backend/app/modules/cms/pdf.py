"""Validación de documentos oficiales antes de publicarlos (WEB-02).

Ningún archivo se publica como PDF si no lo es de verdad: cabecera `%PDF-`, tipo detectado por
magic bytes, estructura que `pypdf` puede abrir, sin cifrar, con al menos una página legible y
sin contenido activo (JavaScript, acciones automáticas, lanzadores ni archivos embebidos).
"""

import hashlib
import io

import anyio
import magic
from fastapi import UploadFile
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import DictionaryObject

from app.modules.pagos.storage import (
    CHUNK,
    ArchivoInvalidoError,
    ArchivoValidado,
    nombre_original_seguro,
)

# Marcadores de contenido activo: un documento institucional no los necesita.
ACTIVOS = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/OpenAction", b"/AA", b"/XFA")


def _inspeccionar(contenido: bytes) -> int:
    """Devuelve la cantidad de páginas o lanza `ArchivoInvalidoError`."""
    if not contenido.startswith(b"%PDF-"):
        raise ArchivoInvalidoError("El archivo no es un PDF (cabecera inválida).", status=415)
    if magic.from_buffer(contenido[:2048], mime=True) != "application/pdf":
        raise ArchivoInvalidoError("El archivo no es un PDF.", status=415)
    if any(marca in contenido for marca in ACTIVOS):
        raise ArchivoInvalidoError(
            "El PDF tiene contenido activo (scripts, acciones automáticas o archivos "
            "embebidos). Exportalo de nuevo como PDF simple.",
            status=422,
        )
    try:
        reader = PdfReader(io.BytesIO(contenido), strict=False)
        if reader.is_encrypted:
            raise ArchivoInvalidoError(
                "El PDF está protegido con contraseña: publicá una versión sin cifrar.",
                status=422,
            )
        raiz = reader.trailer["/Root"].get_object()
        # `[]` resuelve referencias indirectas (`.get` no).
        nombres = (
            raiz["/Names"] if isinstance(raiz, DictionaryObject) and "/Names" in raiz else None
        )
        if not isinstance(raiz, DictionaryObject) or (
            any(clave in raiz for clave in ("/OpenAction", "/AA", "/AcroForm"))
            or (isinstance(nombres, DictionaryObject) and "/JavaScript" in nombres)
        ):
            raise ArchivoInvalidoError(
                "El PDF tiene acciones o formularios activos. Exportalo como PDF simple.",
                status=422,
            )
        paginas = len(reader.pages)
        if paginas == 0:
            raise ArchivoInvalidoError("El PDF no tiene páginas.", status=422)
        reader.pages[0].extract_text()
    except ArchivoInvalidoError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise ArchivoInvalidoError("El PDF está dañado o no se puede abrir.", status=422) from exc
    return paginas


async def validar_pdf(file: UploadFile, max_bytes: int) -> tuple[ArchivoValidado, int]:
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
    paginas = await anyio.to_thread.run_sync(_inspeccionar, contenido)
    archivo = ArchivoValidado(
        contenido=contenido,
        mime_type="application/pdf",
        extension=".pdf",
        sha256=hashlib.sha256(contenido).hexdigest(),
        nombre_original=nombre_original_seguro(file.filename),
    )
    return archivo, paginas
