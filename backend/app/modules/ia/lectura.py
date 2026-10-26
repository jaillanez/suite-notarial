"""Lectura local de documentos: texto de PDF, OCR de imágenes (Tesseract) y códigos PDF417.

Todo corre en el servidor de la Caja, sin servicios externos (módulo 10 §1.1, Ley 25.326). Los
archivos llegan validados por magic bytes (regla MIME) y no se guardan: de la entrada quedan
solo metadatos y su SHA-256.
"""

import hashlib
import io
import re
import shutil
import subprocess
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import anyio
import zxingcpp
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import Configuration, PdfReader, apply_configuration
from pypdf.errors import LimitReachedError, PdfReadError

from app.core.config import get_settings
from app.modules.pagos.storage import ArchivoInvalidoError, ArchivoValidado

# Una foto de celular ronda los 12 MP; el tope evita "bombas" de descompresión.
MAX_PIXELES = 40_000_000
MAX_PAGINAS_PDF = 50
# Todo lo que el PDF puede descomprimir (cualquier stream): una minuta de texto ocupa decenas
# de KB por página. Se mide ANTES de que pypdf abra el archivo.
MAX_INFLADO_PDF = 16 * 1024 * 1024
MAX_STREAMS_PDF = 5_000
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


# Misma sintaxis que acepta pypdf: "stream", espacios opcionales y fin de línea.
_INICIO_STREAM = re.compile(rb"(?<!end)stream[ \t]*(?:\r\n|\r|\n)")
_FILTRO = re.compile(rb"/([A-Za-z0-9]+Decode)\b")
_LARGO_DIRECTO = re.compile(rb"/Length\s+(\d{1,10})(?!\s+\d+\s+R)")
# Imágenes: extraer texto no las decodifica; cuentan lo que pesan.
_FILTROS_IMAGEN = frozenset({b"DCTDecode", b"JPXDecode"})
_VENTANA_DICCIONARIO = 4096


def _diccionario(contenido: memoryview, inicio: int) -> bytes:
    """Bytes del diccionario del stream: desde el último "obj" hasta la palabra "stream"."""
    desde = max(0, inicio - _VENTANA_DICCIONARIO)
    ventana = bytes(contenido[desde:inicio])
    corte = ventana.rfind(b"obj")
    return ventana[corte:] if corte >= 0 else ventana


def _costo_stream(
    contenido: bytes, vista: memoryview, inicio: int, fin_cabecera: int, presupuesto: int
) -> tuple[int, int]:
    """(lo que el stream puede ocupar al decodificarse, bytes examinados). Falla cerrado ante lo
    que no puede medir."""
    diccionario = _diccionario(vista, inicio)
    filtros = _FILTRO.findall(diccionario)
    largo = _LARGO_DIRECTO.search(diccionario)
    if largo is not None:
        fin = min(len(contenido), fin_cabecera + int(largo.group(1)))
    else:
        # /Length indirecto: hasta "endstream" (puede quedar corto; se cobra el tope abajo).
        fin = contenido.find(b"endstream", fin_cabecera)
        fin = len(contenido) if fin < 0 else fin
    datos = vista[fin_cabecera:fin]
    if not filtros or all(f in _FILTROS_IMAGEN for f in filtros):
        return len(datos), len(datos)
    if filtros != [b"FlateDecode"]:
        # Una minuta de texto no necesita otras compresiones ni cadenas de filtros (los
        # predictores de /DecodeParms no amplifican: el tamaño inflado ya los cubre).
        raise ArchivoInvalidoError(
            "El PDF usa una compresión que no se admite: exportalo de nuevo como PDF simple.",
            status=422,
        )
    descompresor = zlib.decompressobj()
    try:
        tamano = len(descompresor.decompress(datos, presupuesto + 1))
    except zlib.error as exc:
        raise ArchivoInvalidoError("El PDF está dañado o no se puede abrir.", status=422) from exc
    if not descompresor.eof and tamano <= presupuesto:
        # No se pudo medir hasta el final: se cobra el máximo que pypdf permite por stream.
        return max(tamano, _POR_STREAM), len(datos)
    return tamano, len(datos)


def _controlar_inflado(contenido: bytes) -> None:
    """Antes de que pypdf abra el archivo: cobra cada `stream` (contenidos, fuentes, streams de
    objetos y de xref) contra un presupuesto total; lo que no puede medir lo cobra al máximo."""
    vista = memoryview(contenido)
    restante = MAX_INFLADO_PDF
    # Los streams no se solapan en un PDF válido: examinar más que dos veces el archivo es abuso.
    examinable = 2 * len(contenido)
    for cantidad, inicio in enumerate(_INICIO_STREAM.finditer(contenido), start=1):
        if cantidad > MAX_STREAMS_PDF:
            raise _demasiado_complejo()
        costo, examinado = _costo_stream(contenido, vista, inicio.start(), inicio.end(), restante)
        restante -= costo
        examinable -= examinado
        if restante < 0 or examinable < 0:
            raise _demasiado_complejo()


# Topes de pypdf mientras se lee una minuta (por stream; el total lo controla el recorrido
# previo). Se aplican solo en el contexto de esta lectura: no cambian la validación del CMS.
_POR_STREAM = 4 * 1024 * 1024
LIMITES_PYPDF = Configuration(
    zlib_maximum_output_length=_POR_STREAM,
    lzw_maximum_output_length=_POR_STREAM,
    run_length_maximum_output_length=_POR_STREAM,
    jbig2_maximum_output_length=_POR_STREAM,
    brotli_maximum_output_length=_POR_STREAM,
    array_based_stream_maximum_output_length=_POR_STREAM,
    image_maximum_buffer_size=_POR_STREAM,
    stream_decoding_work_maximum_length=MAX_INFLADO_PDF,
    xform_maximum_invocations_per_extraction=500,
)


def _texto_pdf(contenido: bytes) -> tuple[str, int]:
    """Texto de un PDF, cortando apenas se pasa de los topes (no después de extraerlo todo)."""
    _controlar_inflado(contenido)
    try:
        with apply_configuration(LIMITES_PYPDF):
            return _leer_pdf(contenido)
    except ArchivoInvalidoError:
        raise
    except (PdfReadError, LimitReachedError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise ArchivoInvalidoError("El PDF está dañado o no se puede abrir.", status=422) from exc


def _leer_pdf(contenido: bytes) -> tuple[str, int]:
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
