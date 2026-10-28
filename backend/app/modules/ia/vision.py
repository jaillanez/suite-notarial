"""Cliente del modelo de visión externo (DeepSeek, API compatible con OpenAI).

Solo transcribe: recibe la foto y devuelve el texto de la respuesta. No ve la DDJJ, el
registro ni datos del sistema; las reglas de negocio se aplican después, localmente
(`indice.py`). La clave viene del entorno (`DEEPSEEK_API_KEY`) y nunca se registra.
"""

import base64
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.modules.ia.indice import PROMPT_VISION


class VisionNoDisponibleError(Exception):
    """El proveedor no está configurado o no respondió bien: se sigue con el OCR local."""


@dataclass(frozen=True)
class LecturaVision:
    texto: str
    modelo: str
    tokens: int | None


def configurada() -> bool:
    settings = get_settings()
    clave = settings.DEEPSEEK_API_KEY
    return settings.IA_VISION_PROVEEDOR == "deepseek" and bool(
        clave and clave.get_secret_value().strip()
    )


async def transcribir(jpeg: bytes) -> LecturaVision:
    settings = get_settings()
    if not configurada() or settings.DEEPSEEK_API_KEY is None:
        raise VisionNoDisponibleError("La lectura por visión no está configurada.")
    imagen = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
    cuerpo = {
        "model": settings.DEEPSEEK_VISION_MODEL,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT_VISION},
                    {"type": "image_url", "image_url": {"url": imagen}},
                ],
            }
        ],
    }
    try:
        async with httpx.AsyncClient(
            base_url=settings.DEEPSEEK_BASE_URL, timeout=settings.IA_VISION_TIMEOUT_S
        ) as cliente:
            respuesta = await cliente.post(
                "/chat/completions",
                json=cuerpo,
                headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY.get_secret_value()}"},
            )
    except httpx.HTTPError as exc:
        raise VisionNoDisponibleError(f"Sin respuesta del proveedor: {type(exc).__name__}") from exc
    if respuesta.status_code != 200:
        # Solo el código: el cuerpo de un error podría repetir partes del pedido.
        raise VisionNoDisponibleError(f"El proveedor respondió {respuesta.status_code}.")
    try:
        datos = respuesta.json()
        texto = datos["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise VisionNoDisponibleError("Respuesta del proveedor con formato inesperado.") from exc
    if not isinstance(texto, str):
        raise VisionNoDisponibleError("Respuesta del proveedor con formato inesperado.")
    uso = datos.get("usage") or {}
    tokens = uso.get("total_tokens")
    return LecturaVision(
        texto=texto,
        modelo=str(datos.get("model") or settings.DEEPSEEK_VISION_MODEL),
        tokens=tokens if isinstance(tokens, int) else None,
    )
