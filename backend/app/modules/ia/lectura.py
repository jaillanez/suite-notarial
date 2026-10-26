"""Lectura local de documentos: texto de PDF, OCR de imágenes (Tesseract) y códigos PDF417.

Todo corre en el servidor de la Caja, sin servicios externos (módulo 10 §1.1, Ley 25.326). Los
archivos llegan validados por magic bytes (regla MIME) y no se guardan: de la entrada quedan
solo metadatos y su SHA-256.
"""

import hashlib
import io
import shutil
import subprocess
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import anyio
import zxingcpp
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import ArrayObject, IndirectObject, StreamObject

from app.core.config import get_settings
from app.modules.pagos.storage import ArchivoInvalidoError, ArchivoValidado

# Una foto de celular ronda los 12 MP; el tope evita "bombas" de descompresión.
MAX_PIXELES = 40_000_000
MAX_PAGINAS_PDF = 50
# Contenido descomprimido de todo el documento (páginas y Form XObjects): una minuta de texto
# ocupa decenas de KB por página. Se mide ANTES de que pypdf infle nada.
MAX_INFLADO_PDF = 16 * 1024 * 1024
MAX_PROFUNDIDAD_XOBJECT = 5
# Mismo tope que el texto pegado (y que el extractor).
MAX_CARACTERES = 200_000
_limitador: anyio.CapacityLimiter | None = None


class OcrNoDisponibleError(Exception):
    pass


class ColaLlenaError(Exception):
    """Demasiadas lecturas esperando: se rechaza en vez de acumular pedidos."""


def _limiter() -> anyio.CapacityLimiter:
    """Pocas lecturas en paralelo: el OCR es costoso y no debe tumbar el servidor."""
    global _limitador  # un único limitador por proceso
    if _limitador is None:
        _limitador = anyio.CapacityLimiter(get_settings().IA_OCR_CONCURRENCIA)
    return _limitador


def _con_lugar() -> anyio.CapacityLimiter:
    limitador = _limiter()
    if limitador.statistics().tasks_waiting >= 4 * get_settings().IA_OCR_CONCURRENCIA:
        raise ColaLlenaError
    return limitador


async def en_hilo[T](funcion: Callable[..., T], *args: object) -> T:
    """Trabajo de CPU (lectura, OCR, extracción) fuera del event loop y con cupo acotado."""
    return await anyio.to_thread.run_sync(funcion, *args, limiter=_con_lugar())


@dataclass(frozen=True)
class Texto:
    contenido: str
    metadatos: dict[str, Any]


@lru_cache
def _idiomas_instalados(comando: str) -> frozenset[str]:
    try:
        salida = subprocess.run(  # noqa: S603 - comando fijo de configuración, sin shell
            [comando, "--list-langs"], capture_output=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    lineas = salida.stdout.decode("utf-8", "replace").splitlines()[1:]
    return frozenset(ln.strip() for ln in lineas if ln.strip())


def estado_ocr() -> tuple[bool, str | None]:
    """(¿hay OCR?, idiomas que se usan). Sin Tesseract siguen funcionando PDF con texto y PDF417."""
    settings = get_settings()
    comando = shutil.which(settings.IA_TESSERACT_CMD)
    if comando is None:
        return False, None
    instalados = _idiomas_instalados(comando)
    pedidos = [i for i in settings.IA_OCR_IDIOMAS.split("+") if i in instalados]
    if not pedidos:
        pedidos = ["eng"] if "eng" in instalados else []
    return bool(pedidos), "+".join(pedidos) or None


def _abrir_imagen(contenido: bytes) -> Image.Image:
    try:
        imagen = Image.open(io.BytesIO(contenido))
        ancho, alto = imagen.size
        if ancho * alto > MAX_PIXELES:
            raise ArchivoInvalidoError(
                "La imagen es demasiado grande: reducí su resolución.", status=413
            )
        imagen.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ArchivoInvalidoError(
            "La imagen está dañada o no se puede abrir.", status=422
        ) from exc
    # Respeta la orientación de la foto (EXIF) y pasa a escala de grises.
    return ImageOps.exif_transpose(imagen).convert("L")


def _png(imagen: Image.Image) -> bytes:
    salida = io.BytesIO()
    imagen.save(salida, "PNG")
    return salida.getvalue()


def _tesseract(imagen: Image.Image, argumentos: list[str]) -> str:
    settings = get_settings()
    disponible, idiomas = estado_ocr()
    comando = shutil.which(settings.IA_TESSERACT_CMD)
    if not disponible or comando is None or idiomas is None:
        raise OcrNoDisponibleError
    try:
        salida = subprocess.run(  # noqa: S603 - binario local fijo; la imagen va por stdin
            [comando, "stdin", "stdout", "-l", idiomas, *argumentos],
            input=_png(imagen),
            capture_output=True,
            timeout=settings.IA_OCR_TIMEOUT_S,
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise ArchivoInvalidoError(
            "La lectura del documento tardó demasiado: probá con una imagen más liviana.",
            status=422,
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise ArchivoInvalidoError("No se pudo leer el texto de la imagen.", status=422) from exc
    return salida.stdout.decode("utf-8", "replace")


def _demasiado_complejo() -> ArchivoInvalidoError:
    return ArchivoInvalidoError(
        "El PDF es demasiado pesado o complejo para leerlo: subí solo la minuta.", status=413
    )


def _inflado(flujo: StreamObject, presupuesto: int) -> int:
    """Bytes que ocupa el stream descomprimido, inflando como mucho `presupuesto + 1` bytes."""
    filtro = flujo.get("/Filter")
    crudo: bytes = getattr(flujo, "_data", b"") or b""
    if filtro is None:
        return len(crudo)
    if isinstance(filtro, ArrayObject):
        filtro = filtro[0] if len(filtro) == 1 else None
    if filtro != "/FlateDecode" or flujo.get("/DecodeParms") is not None:
        # Una minuta de texto no necesita otras compresiones ni predictores.
        raise ArchivoInvalidoError(
            "El PDF usa una compresión que no se admite: exportalo de nuevo como PDF simple.",
            status=422,
        )
    try:
        salida = zlib.decompressobj().decompress(crudo, presupuesto + 1)
    except zlib.error as exc:
        raise ArchivoInvalidoError("El PDF está dañado o no se puede abrir.", status=422) from exc
    return len(salida)


def _flujos(recurso: Any, profundidad: int, vistos: set[int]) -> Iterator[StreamObject]:
    """Contenidos de una página o Form XObject y, recursivamente, los Form XObjects que usa."""
    if profundidad > MAX_PROFUNDIDAD_XOBJECT:
        raise _demasiado_complejo()
    contenidos = recurso.get("/Contents")
    if contenidos is not None:
        contenidos = contenidos.get_object()
        for item in contenidos if isinstance(contenidos, ArrayObject) else [contenidos]:
            flujo = item.get_object()
            if isinstance(flujo, StreamObject):
                yield flujo
    recursos = recurso.get("/Resources")
    xobjects = recursos.get_object().get("/XObject") if recursos is not None else None
    if xobjects is None:
        return
    for ref in xobjects.get_object().values():
        if isinstance(ref, IndirectObject):
            if ref.idnum in vistos:
                continue
            vistos.add(ref.idnum)
        xobject = ref.get_object()
        # Las imágenes no se decodifican al extraer texto; los formularios sí.
        if isinstance(xobject, StreamObject) and xobject.get("/Subtype") == "/Form":
            yield xobject
            yield from _flujos(xobject, profundidad + 1, vistos)


def _controlar_inflado(reader: PdfReader) -> None:
    restante = MAX_INFLADO_PDF
    vistos: set[int] = set()
    for page in reader.pages:
        for flujo in _flujos(page, 0, vistos):
            restante -= _inflado(flujo, restante)
            if restante < 0:
                raise _demasiado_complejo()


def _texto_pdf(contenido: bytes) -> tuple[str, int]:
    """Texto de un PDF, cortando apenas se pasa de los topes (no después de extraerlo todo)."""
    try:
        reader = PdfReader(io.BytesIO(contenido), strict=False)
        if reader.is_encrypted:
            raise ArchivoInvalidoError(
                "El PDF está protegido con contraseña: subí una versión sin cifrar.", status=422
            )
        paginas = len(reader.pages)
        if paginas > MAX_PAGINAS_PDF:
            raise ArchivoInvalidoError(
                f"El PDF tiene más de {MAX_PAGINAS_PDF} páginas: subí solo la minuta.", status=422
            )
        _controlar_inflado(reader)
        partes: list[str] = []
        total = 0
        for page in reader.pages:
            texto = page.extract_text() or ""
            total += len(texto)
            if total > MAX_CARACTERES:
                raise ArchivoInvalidoError(
                    "El PDF tiene demasiado texto: subí solo la minuta.", status=413
                )
            partes.append(texto)
    except ArchivoInvalidoError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise ArchivoInvalidoError("El PDF está dañado o no se puede abrir.", status=422) from exc
    return "\n".join(partes), paginas


def _metadatos(archivo: ArchivoValidado, **extra: Any) -> dict[str, Any]:
    return {
        "origen": "archivo",
        "mime_type": archivo.mime_type,
        "bytes": len(archivo.contenido),
        "sha256": archivo.sha256,
        **extra,
    }


def _leer_minuta(archivo: ArchivoValidado) -> Texto:
    if archivo.mime_type == "application/pdf":
        texto, paginas = _texto_pdf(archivo.contenido)
        if len(texto.strip()) < 40:
            raise ArchivoInvalidoError(
                "El PDF no tiene texto seleccionable (parece escaneado): subí una foto o "
                "imagen (PNG o JPG) de la minuta.",
                status=422,
            )
        return Texto(texto, _metadatos(archivo, paginas=paginas, caracteres=len(texto)))
    imagen = _abrir_imagen(archivo.contenido)
    texto = _tesseract(imagen, ["--psm", "3"])
    _, idiomas = estado_ocr()
    return Texto(texto, _metadatos(archivo, ocr=idiomas, caracteres=len(texto)))


async def leer_minuta(archivo: ArchivoValidado) -> Texto:
    return await en_hilo(_leer_minuta, archivo)


@dataclass(frozen=True)
class LecturaDni:
    codigos: list[str]
    lineas_mrz: list[str]
    metadatos: dict[str, Any]


def _leer_dni(archivo: ArchivoValidado, con_mrz: bool) -> LecturaDni:
    if archivo.mime_type == "application/pdf":
        raise ArchivoInvalidoError(
            "Subí una foto (PNG o JPG) del frente o del dorso del DNI.", status=415
        )
    imagen = _abrir_imagen(archivo.contenido)
    codigos = [
        r.text
        for r in zxingcpp.read_barcodes(
            imagen, formats=zxingcpp.BarcodeFormats(zxingcpp.BarcodeFormat.PDF417)
        )
        if r.valid and r.text
    ]
    lineas: list[str] = []
    if not codigos and con_mrz:
        try:
            texto = _tesseract(
                imagen,
                [
                    "--psm",
                    "6",
                    "-c",
                    "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<",
                ],
            )
            lineas = texto.splitlines()
        except OcrNoDisponibleError:
            lineas = []
    metadatos = _metadatos(archivo, codigos_pdf417=len(codigos), lineas_mrz=len(lineas))
    return LecturaDni(codigos, lineas, metadatos)


async def leer_dni(archivo: ArchivoValidado) -> LecturaDni:
    return await en_hilo(_leer_dni, archivo, True)


def metadatos_texto(texto: str) -> dict[str, Any]:
    """Texto pegado: se registra el largo y el hash, no el contenido."""
    return {
        "origen": "texto",
        "caracteres": len(texto),
        "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
    }
