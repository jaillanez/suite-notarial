"""Cliente del botón de pagos Supervielle (APIBANK Recaudaciones, doc. técnica v1.3.4).

- Acceso: token OAuth 2.0 (grant `password`) con usuario, clave, `client_id` y `client_secret`;
  dura 5 minutos y se reutiliza hasta poco antes de vencer. Cada pedido lleva además la cabecera
  `x-ibm-client-id`. Las credenciales vienen del entorno y nunca se registran.
- Los importes viajan y vuelven sin pasar por float (regla FIN): se envían como número JSON
  escrito desde el Decimal y las respuestas se leen con `parse_float=Decimal`.
- La autenticidad de un pago nunca se toma del navegador ni del aviso del banco (que no viene
  firmado): siempre se consulta el estado de la publicación a la API.
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import get_settings
from app.modules.pagos.catalog import ESTADOS_SPV, MEDIOS_SPV, EstadoPagoSPV

# Marcador del importe: json.dumps no escribe un Decimal como número sin pasar por float.
_IMPORTE = "__IMPORTE_DECIMAL__"
# El token se renueva este margen antes de que venza.
MARGEN_TOKEN_S = 30
# Forma del hash de una publicación (un UUID en los ejemplos del banco).
_HASH = re.compile(r"^[A-Za-z0-9-]{8,100}$")


class SupervielleError(Exception):
    """El banco no respondió o respondió algo inesperado."""


def configurado() -> bool:
    s = get_settings()
    secretos = (s.SUPERVIELLE_CLAVE, s.SUPERVIELLE_CLIENT_SECRET, s.SUPERVIELLE_IBM_CLIENT_ID)
    return bool(
        s.SUPERVIELLE_CONVENIO
        and (s.SUPERVIELLE_USUARIO or "").strip()
        and (s.SUPERVIELLE_CLIENT_ID or "").strip()
        and all(x is not None and x.get_secret_value().strip() for x in secretos)
    )


def hash_valido(valor: str) -> bool:
    return bool(_HASH.fullmatch(valor))


def _secreto(valor: Any) -> str:
    if valor is None or not valor.get_secret_value().strip():
        raise SupervielleError("El botón de pagos Supervielle no está configurado.")
    return str(valor.get_secret_value().strip())


class _Token:
    """Token de acceso compartido por los pedidos del proceso."""

    def __init__(self) -> None:
        self.valor: str | None = None
        self.vence_ns = 0
        self._candado: asyncio.Lock | None = None

    def olvidar(self) -> None:
        self.valor = None
        self.vence_ns = 0

    async def obtener(self) -> str:
        if self.valor is not None and time.monotonic_ns() < self.vence_ns:
            return self.valor
        if self._candado is None:
            self._candado = asyncio.Lock()
        async with self._candado:
            if self.valor is not None and time.monotonic_ns() < self.vence_ns:
                return self.valor
            self.valor, duracion = await _pedir_token()
            self.vence_ns = time.monotonic_ns() + max(duracion - MARGEN_TOKEN_S, 0) * 1_000_000_000
            return self.valor


_token = _Token()


async def _pedir_token() -> tuple[str, int]:
    s = get_settings()
    if not configurado():
        raise SupervielleError("El botón de pagos Supervielle no está configurado.")
    datos = {
        "username": (s.SUPERVIELLE_USUARIO or "").strip(),
        "password": _secreto(s.SUPERVIELLE_CLAVE),
        "client_id": (s.SUPERVIELLE_CLIENT_ID or "").strip(),
        "client_secret": _secreto(s.SUPERVIELLE_CLIENT_SECRET),
        "grant_type": "password",
    }
    if s.SUPERVIELLE_SCOPE.strip():
        datos["scope"] = s.SUPERVIELLE_SCOPE.strip()
    try:
        async with httpx.AsyncClient(timeout=s.SUPERVIELLE_TIMEOUT_S) as cliente:
            respuesta = await cliente.post(
                s.SUPERVIELLE_AUTH_URL,
                data=datos,
                headers={"X-Forwarded-Host": s.SUPERVIELLE_FORWARDED_HOST},
            )
    except httpx.HTTPError as exc:
        raise SupervielleError(f"Sin respuesta del banco: {type(exc).__name__}") from exc
    if respuesta.status_code != 200:
        # Solo el código: el cuerpo de un error puede repetir datos del pedido.
        raise SupervielleError(f"El banco respondió {respuesta.status_code} al pedir el token.")
    try:
        cuerpo = respuesta.json()
        valor = str(cuerpo["access_token"])
        duracion = int(cuerpo.get("expires_in") or 300)
    except (ValueError, KeyError, TypeError) as exc:
        raise SupervielleError("Token del banco con formato inesperado.") from exc
    if not valor:
        raise SupervielleError("El banco no devolvió el token.")
    return valor, duracion


async def _pedir(
    metodo: str, ruta: str, *, cuerpo: str | None = None, params: dict[str, str] | None = None
) -> tuple[int, Any]:
    """Pedido a la API con el token. Un 401 renueva el token y reintenta una sola vez.
    Devuelve el código y el cuerpo leído con Decimal."""
    s = get_settings()
    for intento in (1, 2):
        headers = {
            "Authorization": f"Bearer {await _token.obtener()}",
            "x-ibm-client-id": _secreto(s.SUPERVIELLE_IBM_CLIENT_ID),
            "X-Forwarded-Host": s.SUPERVIELLE_FORWARDED_HOST,
            "Accept": "application/json, application/problem+json",
        }
        if cuerpo is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(
                base_url=s.SUPERVIELLE_API_URL.rstrip("/") + "/", timeout=s.SUPERVIELLE_TIMEOUT_S
            ) as cliente:
                respuesta = await cliente.request(
                    metodo, ruta, content=cuerpo, headers=headers, params=params
                )
        except httpx.HTTPError as exc:
            raise SupervielleError(f"Sin respuesta del banco: {type(exc).__name__}") from exc
        if respuesta.status_code == 401 and intento == 1:
            _token.olvidar()
            continue
        break
    try:
        datos = json.loads(respuesta.text, parse_float=Decimal) if respuesta.text else None
    except ValueError:
        datos = None
    return respuesta.status_code, datos


# --------------------------------------------------------------------------- publicación


@dataclass(frozen=True)
class Publicacion:
    hash: str
    link_pago: str


async def publicar(
    *,
    id_publicacion: int,
    importe: Decimal,
    vence: date,
    nombre: str,
    descripcion: str,
    identificadores: list[str],
) -> Publicacion:
    """Publica una deuda «Cerrada» (solo se paga el total) con un único vencimiento."""
    convenio = get_settings().SUPERVIELLE_CONVENIO
    if convenio is None:
        raise SupervielleError("El botón de pagos Supervielle no está configurado.")
    cuerpo: dict[str, Any] = {
        "tipo_publicacion": "Deuda",
        "id_publicacion": id_publicacion,
        "convenio": convenio,
        "modalidad": "Cerrada",
        "importe1": _IMPORTE,
        "fecha_vencimiento1": vence.isoformat(),
        "nombre": nombre[:100],
        "descripcion": descripcion[:200],
        "identificadores": identificadores[:10],
    }
    texto = json.dumps(cuerpo, ensure_ascii=False).replace(f'"{_IMPORTE}"', f"{importe:.2f}")
    codigo, datos = await _pedir("POST", "v1.0/publicaciones/publicacion", cuerpo=texto)
    if codigo != 201:
        raise SupervielleError(f"El banco respondió {codigo} al publicar la deuda.")
    try:
        hash_, link = str(datos["hash"]), str(datos["link_de_pago"]).strip()
    except (KeyError, TypeError) as exc:
        raise SupervielleError("El banco no devolvió el link de pago.") from exc
    if not hash_valido(hash_) or not link.startswith("https://"):
        raise SupervielleError("El banco devolvió un link de pago con formato inesperado.")
    return Publicacion(hash=hash_, link_pago=link)


# --------------------------------------------------------------------------- estado


def _importe(valor: Any) -> Decimal | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _fecha(valor: Any) -> datetime | None:
    if not isinstance(valor, str):
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        return None


def _entero(valor: Any) -> int | None:
    if isinstance(valor, bool):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Pago:
    """Un pago de una publicación, como lo informa el banco, ya tipado."""

    id: str
    estado: EstadoPagoSPV
    id_medio: int | None
    medio_pago: str | None
    importe: Decimal | None
    # Fecha y hora sin zona, tal como la informa el banco (hora de Argentina).
    fecha: datetime | None


def pago_desde(datos: Any) -> Pago:
    if not isinstance(datos, dict) or datos.get("id_pago") is None:
        raise SupervielleError("Pago del banco con formato inesperado.")
    id_estado = _entero(datos.get("id_estado_pago"))
    id_medio = _entero(datos.get("id_medio_pago"))
    medio = MEDIOS_SPV.get(id_medio) if id_medio is not None else None
    if medio is None and datos.get("medio_pago"):
        medio = str(datos["medio_pago"])[:50]
    return Pago(
        id=str(datos["id_pago"])[:50],
        estado=ESTADOS_SPV.get(id_estado, EstadoPagoSPV.PENDIENTE)
        if id_estado is not None
        else EstadoPagoSPV.PENDIENTE,
        id_medio=id_medio,
        medio_pago=medio,
        importe=_importe(datos.get("importe")),
        fecha=_fecha(datos.get("fecha")),
    )


async def pagos_de(hash_: str) -> list[Pago]:
    """Pagos recibidos por una publicación."""
    if not hash_valido(hash_):
        raise SupervielleError("Hash de publicación inválido.")
    codigo, datos = await _pedir("GET", f"v1.0/publicaciones/publicacion/{hash_}/estado")
    if codigo != 200 or not isinstance(datos, dict):
        raise SupervielleError(f"El banco respondió {codigo} al consultar la publicación.")
    pagos = datos.get("pagos") or []
    if not isinstance(pagos, list):
        raise SupervielleError("Estado de la publicación con formato inesperado.")
    return [pago_desde(p) for p in pagos]


# --------------------------------------------------------------------------- rendiciones

# Registros por página al pedir una rendición, y tope de páginas (contra una respuesta que no
# termina nunca).
POR_PAGINA = 100
MAX_PAGINAS = 200


@dataclass(frozen=True)
class PagoRendido:
    """Un pago de la rendición del banco, con la publicación a la que corresponde."""

    hash_publicacion: str
    pago: Pago


def _registros(datos: Any) -> list[Any]:
    # La documentación dice «devuelve un array»; se acepta también un objeto que lo envuelva.
    if isinstance(datos, list):
        return datos
    if isinstance(datos, dict):
        for clave in ("pagos", "items", "data", "resultado"):
            if isinstance(datos.get(clave), list):
                return list(datos[clave])
    raise SupervielleError("Rendición del banco con formato inesperado.")


async def rendicion_pagos(desde: date, hasta: date) -> list[PagoRendido]:
    """Pagos recibidos entre dos fechas (inclusive), de todas las publicaciones del convenio."""
    rendidos: list[PagoRendido] = []
    for pagina in range(1, MAX_PAGINAS + 1):
        codigo, datos = await _pedir(
            "GET",
            "v1.0/rendiciones/pagos",
            params={
                "fecha_desde": desde.isoformat(),
                "fecha_hasta": hasta.isoformat(),
                "page": str(pagina),
                "count": str(POR_PAGINA),
            },
        )
        if codigo == 404 and pagina > 1:
            break
        if codigo != 200:
            raise SupervielleError(f"El banco respondió {codigo} al pedir la rendición.")
        registros = _registros(datos)
        for r in registros:
            if not isinstance(r, dict) or not r.get("hash_publicacion"):
                continue
            # La rendición informa la fecha del pago como `fecha_pago`.
            pago = pago_desde({**r, "fecha": r.get("fecha_pago", r.get("fecha"))})
            rendidos.append(PagoRendido(str(r["hash_publicacion"])[:100], pago))
        if len(registros) < POR_PAGINA:
            break
    return rendidos


async def probar_acceso() -> None:
    """Pide un token: confirma usuario, clave, client_id y client_secret (no publica nada)."""
    _token.olvidar()
    await _token.obtener()


def faltantes() -> list[str]:
    """Variables de configuración que faltan para habilitar el botón."""
    s = get_settings()
    textos = {
        "SUPERVIELLE_USUARIO": s.SUPERVIELLE_USUARIO,
        "SUPERVIELLE_CLIENT_ID": s.SUPERVIELLE_CLIENT_ID,
    }
    secretos = {
        "SUPERVIELLE_CLAVE": s.SUPERVIELLE_CLAVE,
        "SUPERVIELLE_CLIENT_SECRET": s.SUPERVIELLE_CLIENT_SECRET,
        "SUPERVIELLE_IBM_CLIENT_ID": s.SUPERVIELLE_IBM_CLIENT_ID,
    }
    faltan = [k for k, v in textos.items() if not (v or "").strip()]
    faltan += [k for k, v in secretos.items() if v is None or not v.get_secret_value().strip()]
    if s.SUPERVIELLE_CONVENIO is None:
        faltan.append("SUPERVIELLE_CONVENIO")
    return sorted(faltan)


def es_ambiente_de_pruebas() -> bool:
    return "apitst." in get_settings().SUPERVIELLE_API_URL
