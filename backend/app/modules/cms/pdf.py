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
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, PdfObject

from app.modules.pagos.storage import (
    CHUNK,
    ArchivoInvalidoError,
    ArchivoValidado,
    nombre_original_seguro,
)

# Marcadores de contenido activo: un documento institucional no los necesita. El escaneo de
# bytes es un primer filtro; el control de fondo recorre el grafo de objetos ya parseado.
ACTIVOS = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/OpenAction", b"/AA", b"/XFA")
CLAVES_PROHIBIDAS = frozenset(
    {
        "/JS",
        "/JavaScript",
        "/OpenAction",
        "/AA",
        "/AcroForm",
        "/XFA",
        "/EmbeddedFile",
        "/EmbeddedFiles",
        "/RichMedia",
        "/RichMediaContent",
    }
)
ACCIONES_PROHIBIDAS = frozenset(
    {
        "/JavaScript",
        "/Launch",
        "/SubmitForm",
        "/ImportData",
        "/GoToR",
        "/GoToE",
        "/Movie",
        "/Sound",
        "/Rendition",
        "/RichMediaExecute",
    }
)
SUBTIPOS_PROHIBIDOS = frozenset(
    {"/FileAttachment", "/RichMedia", "/Movie", "/Sound", "/Screen", "/3D"}
)
MAX_OBJETOS = 200_000


def _activo(raiz: PdfObject) -> str | None:
    """Recorre el grafo desde el catálogo (resolviendo referencias) buscando contenido activo.

    pypdf ya decodificó los nombres (`/Java#53cript` llega como `/JavaScript`).
    """
    pendientes: list[PdfObject] = [raiz]
    vistos: set[tuple[int, int]] = set()
    revisados = 0
    while pendientes:
        obj: PdfObject | None = pendientes.pop()
        if isinstance(obj, IndirectObject):
            clave = (obj.idnum, obj.generation)
            if clave in vistos:
                continue
            vistos.add(clave)
            obj = obj.get_object()
        revisados += 1
        if revisados > MAX_OBJETOS:
            return "estructura demasiado compleja"
        if isinstance(obj, DictionaryObject):
            for k in obj:
                if k in CLAVES_PROHIBIDAS:
                    return str(k)
            accion = obj.get("/S")
            if accion in ACCIONES_PROHIBIDAS:
                return str(accion)
            if obj.get("/Subtype") in SUBTIPOS_PROHIBIDOS:
                return str(obj.get("/Subtype"))
            # Valores sin resolver: las referencias se resuelven al sacarlas de la pila.
            pendientes.extend(obj.values())
        elif isinstance(obj, ArrayObject):
            pendientes.extend(obj)
    return None


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
        hallazgo = _activo(reader.trailer["/Root"])
        if hallazgo is not None:
            raise ArchivoInvalidoError(
                "El PDF tiene contenido activo (scripts, acciones, formularios o archivos "
                "embebidos). Exportalo de nuevo como PDF simple.",
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
