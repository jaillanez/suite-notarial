"""Cliente de la API de Mercado Pago (Checkout Pro y consulta de pagos).

- Los importes viajan y vuelven sin pasar por float (regla FIN): se envían como número JSON
  escrito desde el Decimal y las respuestas se leen con `parse_float=Decimal`.
- El token es de la cuenta de la Caja y viene del entorno; nunca se registra.
- La autenticidad de un pago no se toma del navegador ni de la notificación: siempre se
  consulta el pago a la API con el token.
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import get_settings

# Marcador del importe: json.dumps no escribe un Decimal como número sin pasar por float.
_IMPORTE = "__IMPORTE_DECIMAL__"


class MercadoPagoError(Exception):
    """Mercado Pago no respondió o respondió algo inesperado."""


def configurado() -> bool:
    token = get_settings().MERCADOPAGO_ACCESS_TOKEN
    return bool(token and token.get_secret_value().strip())


def _token() -> str:
    token = get_settings().MERCADOPAGO_ACCESS_TOKEN
    if token is None or not token.get_secret_value().strip():
        raise MercadoPagoError("Mercado Pago no está configurado.")
    return token.get_secret_value().strip()


async def _pedir(
    metodo: str, ruta: str, *, cuerpo: str | None = None, params: dict[str, str] | None = None
) -> Any:
    settings = get_settings()
    headers = {"Authorization": f"Bearer {_token()}"}
    if cuerpo is not None:
        headers["Content-Type"] = "application/json"
    try:
        async with httpx.AsyncClient(
            base_url=settings.MERCADOPAGO_BASE_URL, timeout=settings.MERCADOPAGO_TIMEOUT_S
        ) as cliente:
            respuesta = await cliente.request(
                metodo, ruta, content=cuerpo, headers=headers, params=params
            )
    except httpx.HTTPError as exc:
        raise MercadoPagoError(f"Sin respuesta de Mercado Pago: {type(exc).__name__}") from exc
    if respuesta.status_code >= 400:
        # Solo el código: el cuerpo de un error puede repetir datos del pedido.
        raise MercadoPagoError(f"Mercado Pago respondió {respuesta.status_code}.")
    try:
        return json.loads(respuesta.text, parse_float=Decimal)
    except ValueError as exc:
        raise MercadoPagoError("Respuesta de Mercado Pago con formato inesperado.") from exc


@dataclass(frozen=True)
class Preferencia:
    id: str
    url_pago: str


async def crear_preferencia(
    *,
    referencia: str,
    titulo: str,
    importe: Decimal,
    vence: datetime,
    url_retorno: str,
    url_notificacion: str | None,
    retorno_automatico: bool,
) -> Preferencia:
    """Cobro de Checkout Pro por un único ítem: el total exacto de la boleta."""
    cuerpo: dict[str, Any] = {
        "items": [
            {
                "id": referencia,
                "title": titulo,
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": _IMPORTE,
            }
        ],
        "external_reference": referencia,
        "back_urls": {"success": url_retorno, "failure": url_retorno, "pending": url_retorno},
        # Después de la fecha de pago de la boleta corre la mora: el cobro deja de servir.
        "expires": True,
        "expiration_date_to": vence.isoformat(timespec="milliseconds"),
        "date_of_expiration": vence.isoformat(timespec="milliseconds"),
        "binary_mode": False,
        "statement_descriptor": "CAJA NOTARIAL SJ",
    }
    if retorno_automatico:
        cuerpo["auto_return"] = "approved"
    if url_notificacion:
        cuerpo["notification_url"] = url_notificacion
    texto = json.dumps(cuerpo).replace(f'"{_IMPORTE}"', f"{importe:.2f}")
    datos = await _pedir("POST", "/checkout/preferences", cuerpo=texto)
    try:
        return Preferencia(id=str(datos["id"]), url_pago=str(datos["init_point"]))
    except (KeyError, TypeError) as exc:
        raise MercadoPagoError("Mercado Pago no devolvió el cobro.") from exc


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


@dataclass(frozen=True)
class Pago:
    """Lo que interesa de un pago de Mercado Pago, ya tipado."""

    id: str
    estado: str
    estado_detalle: str | None
    referencia: str | None
    moneda: str | None
    importe: Decimal | None
    comision: Decimal | None
    neto: Decimal | None
    medio_pago: str | None
    aprobado_en: datetime | None

    @property
    def fecha_aprobacion(self) -> date | None:
        return self.aprobado_en.date() if self.aprobado_en else None


def pago_desde(datos: Any) -> Pago:
    if not isinstance(datos, dict) or "id" not in datos or "status" not in datos:
        raise MercadoPagoError("Pago de Mercado Pago con formato inesperado.")
    comisiones = [
        _importe(f.get("amount")) for f in datos.get("fee_details") or [] if isinstance(f, dict)
    ]
    detalles = datos.get("transaction_details") or {}
    return Pago(
        id=str(datos["id"]),
        estado=str(datos["status"]),
        estado_detalle=(str(datos["status_detail"])[:100] if datos.get("status_detail") else None),
        referencia=(str(datos["external_reference"]) if datos.get("external_reference") else None),
        moneda=datos.get("currency_id"),
        importe=_importe(datos.get("transaction_amount")),
        comision=sum((c for c in comisiones if c is not None), Decimal("0.00"))
        if comisiones
        else None,
        neto=_importe(detalles.get("net_received_amount")) if isinstance(detalles, dict) else None,
        medio_pago=(
            str(datos["payment_method_id"])[:50] if datos.get("payment_method_id") else None
        ),
        aprobado_en=_fecha(datos.get("date_approved")),
    )


async def obtener_pago(pago_id: str) -> Pago:
    if not pago_id.isdigit():
        raise MercadoPagoError("Identificador de pago inválido.")
    return pago_desde(await _pedir("GET", f"/v1/payments/{pago_id}"))


async def pagos_de(referencia: str) -> list[Pago]:
    """Pagos de un cobro, por su `external_reference` (el id de nuestro registro)."""
    datos = await _pedir(
        "GET",
        "/v1/payments/search",
        params={"external_reference": referencia, "sort": "date_created", "criteria": "desc"},
    )
    resultados = datos.get("results") if isinstance(datos, dict) else None
    return [pago_desde(r) for r in resultados or []]


# Antigüedad máxima de una notificación (contra repeticiones de una ya enviada).
VENTANA_FIRMA_S = 600


def firma_valida(
    *,
    firma: str | None,
    request_id: str | None,
    data_id: str,
    secreto: str,
    ahora: int | None = None,
) -> bool:
    """Verifica la cabecera `x-signature` de una notificación (HMAC-SHA256 de Mercado Pago):
    `ts=...,v1=...` sobre `id:{data.id};request-id:{x-request-id};ts:{ts};`. Exige el
    `x-request-id` y rechaza notificaciones de más de 10 minutos."""
    if not firma or not request_id:
        return False
    partes = dict(p.split("=", 1) for p in firma.split(",") if "=" in p)
    ts, v1 = partes.get("ts", "").strip(), partes.get("v1", "").strip()
    if not ts.isdigit() or not v1:
        return False
    # Mercado Pago informa el momento en segundos o en milisegundos.
    segundos = int(ts) // 1000 if len(ts) > 11 else int(ts)
    if abs((int(time.time()) if ahora is None else ahora) - segundos) > VENTANA_FIRMA_S:
        return False
    manifiesto = f"id:{data_id.lower()};request-id:{request_id};ts:{ts};"
    esperada = hmac.new(secreto.encode(), manifiesto.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, v1)
