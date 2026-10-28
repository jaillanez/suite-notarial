"""Pago de boletas con Mercado Pago: el pago se registra y queda en revisión; Tesorería lo
confirma. Mercado Pago se simula (ningún test llama a su API); los pagos simulados pasan por el
mismo parser que las respuestas reales."""

# ruff: noqa: F811

import hashlib
import hmac
import json
import time
import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.core.config import Environment, Settings, get_settings
from app.modules.pagos import mercadopago, mercadopago_service
from app.modules.pagos.models import Comprobante, PagoMercadoPago
from tests.ddjj.conftest import HOY, Escenario, _client, _escribano
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.pagos.conftest import boleta, tesoreria  # noqa: F401 - fixtures compartidas


class MercadoPagoFalso:
    """Lo que la Suite le pide a Mercado Pago y lo que Mercado Pago contestaría."""

    def __init__(self) -> None:
        self.cobros: list[dict[str, Any]] = []
        self.pagos: dict[str, list[dict[str, Any]]] = {}

    async def crear_preferencia(self, **datos: Any) -> mercadopago.Preferencia:
        self.cobros.append(datos)
        n = len(self.cobros)
        return mercadopago.Preferencia(f"pref-{n}", f"https://mp.test/checkout/{n}")

    def informar(self, referencia: str, **campos: Any) -> dict[str, Any]:
        """Pago tal como lo devuelve la API (JSON), con los números como en la respuesta."""
        pago: dict[str, Any] = {
            "id": 1000 + sum(len(p) for p in self.pagos.values()),
            "status": "approved",
            "status_detail": "accredited",
            "external_reference": referencia,
            "currency_id": "ARS",
            "transaction_amount": None,
            "payment_method_id": "account_money",
            "date_approved": "2026-10-23T10:15:00.000-03:00",
            "fee_details": [{"type": "mercadopago_fee", "amount": 1234.56}],
            "transaction_details": {"net_received_amount": None},
            **campos,
        }
        self.pagos.setdefault(referencia, []).append(pago)
        return pago

    def _parse(self, pago: dict[str, Any]) -> mercadopago.Pago:
        # Mismo camino que una respuesta real: texto JSON leído con Decimal.
        return mercadopago.pago_desde(
            json.loads(json.dumps(pago, default=str), parse_float=Decimal)
        )

    async def pagos_de(self, referencia: str) -> list[mercadopago.Pago]:
        return [self._parse(p) for p in self.pagos.get(referencia, [])]

    async def obtener_pago(self, pago_id: str) -> mercadopago.Pago:
        for lista in self.pagos.values():
            for p in lista:
                if str(p["id"]) == pago_id:
                    return self._parse(p)
        raise mercadopago.MercadoPagoError("Mercado Pago respondió 404.")


@pytest.fixture
def mp(monkeypatch: pytest.MonkeyPatch) -> MercadoPagoFalso:
    falso = MercadoPagoFalso()
    monkeypatch.setattr(get_settings(), "MERCADOPAGO_ACCESS_TOKEN", SecretStr("TEST-token"))
    monkeypatch.setattr(mercadopago_service, "today_local", lambda: HOY)
    monkeypatch.setattr(mercadopago, "crear_preferencia", falso.crear_preferencia)
    monkeypatch.setattr(mercadopago, "pagos_de", falso.pagos_de)
    monkeypatch.setattr(mercadopago, "obtener_pago", falso.obtener_pago)
    return falso


async def _pagar(cliente: AsyncClient, boleta_id: str) -> Any:
    return await cliente.post(f"/api/v1/pagos/boletas/{boleta_id}/mercadopago")


async def _pago_mp(session: AsyncSession, boleta_id: str) -> PagoMercadoPago:
    item = await session.scalar(
        select(PagoMercadoPago)
        .where(PagoMercadoPago.boleta_id == uuid.UUID(boleta_id))
        .order_by(PagoMercadoPago.created_at.desc())
    )
    assert item is not None
    await session.refresh(item)
    return item


async def _eventos(session: AsyncSession, tipo: str) -> list[dict[str, Any]]:
    filas = await session.scalars(
        select(AuditSecurityLog.details).where(AuditSecurityLog.event_type == tipo)
    )
    return [d or {} for d in filas.all()]


# --------------------------------------------------------------------------- reglas sin red


def test_el_pago_se_lee_sin_flotantes() -> None:
    texto = '{"id": 77, "status": "approved", "transaction_amount": 341211.07,'
    texto += ' "fee_details": [{"amount": 1.1}, {"amount": 2.2}],'
    texto += ' "transaction_details": {"net_received_amount": 341207.77}}'
    pago = mercadopago.pago_desde(json.loads(texto, parse_float=Decimal))
    assert pago.importe == Decimal("341211.07")
    # 1.1 + 2.2 en float da 3.3000000000000003.
    assert pago.comision == Decimal("3.30")
    assert pago.neto == Decimal("341207.77")


def test_firma_de_la_notificacion() -> None:
    ahora = 1792724400
    manifiesto = f"id:123;request-id:req-1;ts:{ahora};"
    v1 = hmac.new(b"secreto", manifiesto.encode(), hashlib.sha256).hexdigest()
    firma = f"ts={ahora},v1={v1}"

    def valida(**cambios: Any) -> bool:
        datos: dict[str, Any] = {
            "firma": firma,
            "request_id": "req-1",
            "data_id": "123",
            "secreto": "secreto",
            "ahora": ahora + 30,
        }
        return mercadopago.firma_valida(**(datos | cambios))

    assert valida()
    assert not valida(data_id="124")
    assert not valida(firma=None)
    # Sin x-request-id no se acepta, y una notificación vieja tampoco (repetición).
    assert not valida(request_id=None)
    assert not valida(ahora=ahora + mercadopago.VENTANA_FIRMA_S + 1)
    # Mercado Pago puede informar el momento en milisegundos.
    ms = f"{ahora}000"
    v1_ms = hmac.new(
        b"secreto", f"id:123;request-id:req-1;ts:{ms};".encode(), hashlib.sha256
    ).hexdigest()
    assert valida(firma=f"ts={ms},v1={v1_ms}")


@pytest.mark.parametrize("env", [Environment.STAGING, Environment.PRODUCTION])
def test_fuera_de_desarrollo_la_clave_de_notificaciones_es_obligatoria(env: Environment) -> None:
    with pytest.raises(ValueError, match="MERCADOPAGO_WEBHOOK_SECRET"):
        Settings(
            ENVIRONMENT=env,
            PUBLIC_WEB_URL="https://suite.cajanotarial-sj.com.ar",
            SMTP_SECURITY="tls",
            MERCADOPAGO_ACCESS_TOKEN="APP_USR-token",
        )


# --------------------------------------------------------------------------- flujo


async def test_sin_token_no_se_ofrece(notario: AsyncClient, boleta: dict[str, Any]) -> None:
    assert (await notario.get("/api/v1/pagos/mercadopago/estado")).json() == {"habilitado": False}
    assert (await _pagar(notario, boleta["id"])).status_code == 503


async def test_pagar_registra_y_tesoreria_confirma(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
    mp: MercadoPagoFalso,
    db_session: AsyncSession,
) -> None:
    assert (await notario.get("/api/v1/pagos/mercadopago/estado")).json() == {"habilitado": True}
    respuesta = await _pagar(notario, boleta["id"])
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["url_pago"] == "https://mp.test/checkout/1"

    # Se cobra el total exacto (la comisión la absorbe la Caja) y vence con la boleta.
    cobro = mp.cobros[0]
    assert cobro["importe"] == Decimal(boleta["total_a_pagar"])
    assert cobro["vence"].date().isoformat() == boleta["fecha_pago"]
    assert cobro["vence"].utcoffset().total_seconds() == -3 * 3600
    # Con la Suite publicada en HTTPS, Mercado Pago avisa a la ruta de notificaciones.
    assert cobro["url_notificacion"].endswith("/api/v1/pagos/mercadopago/notificaciones")
    assert cobro["url_notificacion"].startswith("https://")
    registro = await _pago_mp(db_session, boleta["id"])
    assert registro.estado == "CREADO"
    assert f"pago={registro.id}" in cobro["url_retorno"]

    # Mercado Pago aprueba; al volver, la Suite le pregunta y registra.
    mp.informar(
        str(registro.id),
        transaction_amount=Decimal(boleta["total_a_pagar"]),
        transaction_details={"net_received_amount": 1.0},
    )
    sincronizado = await notario.post(f"/api/v1/pagos/mercadopago/{registro.id}/sincronizar")
    assert sincronizado.status_code == 200, sincronizado.text
    assert sincronizado.json()["estado"] == "approved"
    # Comisión y neto son datos internos de la Caja: el escribano no los ve.
    assert sincronizado.json()["comision"] is None
    assert sincronizado.json()["importe_neto"] is None

    # El pago queda en la mesa de Tesorería; la boleta todavía no está pagada.
    comprobante = await db_session.scalar(
        select(Comprobante).where(Comprobante.boleta_id == uuid.UUID(boleta["id"]))
    )
    assert comprobante is not None
    assert comprobante.origen == "MERCADO_PAGO"
    assert comprobante.estado == "PENDIENTE_REVISION"
    assert comprobante.archivo is None
    detalle = (await notario.get(f"/api/v1/ddjj/boletas/{boleta['id']}")).json()
    assert detalle["estado"] == "PENDIENTE"
    assert detalle["comprobante"]["estado"] == "PENDIENTE_REVISION"
    # Mientras tanto no se puede iniciar otro pago.
    assert (await _pagar(notario, boleta["id"])).status_code == 409
    # Volver a consultar no duplica nada.
    await notario.post(f"/api/v1/pagos/mercadopago/{registro.id}/sincronizar")
    assert len((await db_session.scalars(select(Comprobante))).all()) == 1

    # Tesorería lo ve con los datos de Mercado Pago, sin archivo, y lo confirma.
    visto = (await tesoreria.get(f"/api/v1/pagos/comprobantes/{comprobante.id}")).json()
    assert visto["origen"] == "MERCADO_PAGO"
    assert visto["mercado_pago"]["mp_payment_id"] == str(mp.pagos[str(registro.id)][0]["id"])
    assert visto["mercado_pago"]["comision"] == "1234.56"
    assert visto["diferencia"] == "0.00"
    sin_archivo = await tesoreria.get(f"/api/v1/pagos/comprobantes/{comprobante.id}/archivo")
    assert sin_archivo.status_code == 404
    aprobado = await tesoreria.post(
        f"/api/v1/pagos/comprobantes/{comprobante.id}/aprobar",
        json={
            "importe_confirmado": boleta["total_a_pagar"],
            "fecha_acreditacion": "2026-10-23",
            "identificador_extracto": "MP liquidación 23/10",
        },
    )
    assert aprobado.status_code == 200, aprobado.text
    assert (await notario.get(f"/api/v1/ddjj/boletas/{boleta['id']}")).json()["estado"] == "PAGADA"

    assert len(await _eventos(db_session, "PAGO_MP_INICIADO")) == 1
    acreditados = await _eventos(db_session, "PAGO_MP_ACREDITADO")
    assert len(acreditados) == 1 and acreditados[0]["importe_coincide"] is True


async def test_rechazado_no_genera_comprobante_y_despues_aprobado_si(
    notario: AsyncClient, boleta: dict[str, Any], mp: MercadoPagoFalso, db_session: AsyncSession
) -> None:
    await _pagar(notario, boleta["id"])
    registro = await _pago_mp(db_session, boleta["id"])
    mp.informar(
        str(registro.id), status="rejected", status_detail="cc_rejected_insufficient_amount"
    )
    rechazado = await notario.post(f"/api/v1/pagos/mercadopago/{registro.id}/sincronizar")
    assert rechazado.json()["estado"] == "rejected"
    assert (await db_session.scalars(select(Comprobante))).all() == []

    mp.informar(str(registro.id), transaction_amount=Decimal(boleta["total_a_pagar"]))
    aprobado = await notario.post(f"/api/v1/pagos/mercadopago/{registro.id}/sincronizar")
    assert aprobado.json()["estado"] == "approved"
    assert len((await db_session.scalars(select(Comprobante))).all()) == 1


async def test_importe_distinto_va_a_tesoreria_con_aviso(
    notario: AsyncClient, boleta: dict[str, Any], mp: MercadoPagoFalso, db_session: AsyncSession
) -> None:
    await _pagar(notario, boleta["id"])
    registro = await _pago_mp(db_session, boleta["id"])
    mp.informar(str(registro.id), transaction_amount=10.0)
    await notario.post(f"/api/v1/pagos/mercadopago/{registro.id}/sincronizar")
    comprobante = await db_session.scalar(select(Comprobante))
    assert comprobante is not None
    assert comprobante.importe_declarado == Decimal("10.00")
    assert (await _eventos(db_session, "PAGO_MP_ACREDITADO"))[0]["importe_coincide"] is False


async def test_devolucion_posterior_queda_como_alerta(
    notario: AsyncClient, boleta: dict[str, Any], mp: MercadoPagoFalso, db_session: AsyncSession
) -> None:
    await _pagar(notario, boleta["id"])
    registro = await _pago_mp(db_session, boleta["id"])
    pago = mp.informar(str(registro.id), transaction_amount=Decimal(boleta["total_a_pagar"]))
    await notario.post(f"/api/v1/pagos/mercadopago/{registro.id}/sincronizar")
    pago["status"] = "refunded"
    devuelto = await notario.post(f"/api/v1/pagos/mercadopago/{registro.id}/sincronizar")
    assert devuelto.json()["estado"] == "refunded"
    assert len(await _eventos(db_session, "PAGO_MP_REVERTIDO")) == 1


async def test_pago_doble_no_genera_otro_comprobante(
    notario: AsyncClient, boleta: dict[str, Any], mp: MercadoPagoFalso, db_session: AsyncSession
) -> None:
    await _pagar(notario, boleta["id"])
    registro = await _pago_mp(db_session, boleta["id"])
    total = Decimal(boleta["total_a_pagar"])
    mp.informar(str(registro.id), transaction_amount=total)
    await notario.post(f"/api/v1/pagos/mercadopago/{registro.id}/sincronizar")
    mp.informar(str(registro.id), transaction_amount=total)
    await notario.post(f"/api/v1/pagos/mercadopago/{registro.id}/sincronizar")
    assert len((await db_session.scalars(select(Comprobante))).all()) == 1
    assert len(await _eventos(db_session, "PAGO_MP_DUPLICADO")) == 1


async def test_notificacion_firmada_sin_sesion(
    app: FastAPI,
    notario: AsyncClient,
    boleta: dict[str, Any],
    mp: MercadoPagoFalso,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _pagar(notario, boleta["id"])
    registro = await _pago_mp(db_session, boleta["id"])
    pago = mp.informar(str(registro.id), transaction_amount=Decimal(boleta["total_a_pagar"]))
    data_id = str(pago["id"])
    ts = str(int(time.time()))
    v1 = hmac.new(
        b"secreto-mp", f"id:{data_id};request-id:req-9;ts:{ts};".encode(), hashlib.sha256
    ).hexdigest()
    # Mercado Pago llama sin cookies ni la cabecera anti-CSRF de la Suite.
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("198.51.100.7", 443)), base_url="https://test"
    ) as externo:
        url = f"/api/v1/pagos/mercadopago/notificaciones?type=payment&data.id={data_id}"
        # Sin clave secreta configurada no se atiende ninguna notificación.
        sin_clave = await externo.post(
            url, headers={"x-signature": f"ts={ts},v1={v1}", "x-request-id": "req-9"}
        )
        assert sin_clave.status_code == 401
        monkeypatch.setattr(get_settings(), "MERCADOPAGO_WEBHOOK_SECRET", SecretStr("secreto-mp"))
        falsa = await externo.post(
            url, headers={"x-signature": f"ts={ts},v1=00", "x-request-id": "req-9"}
        )
        assert falsa.status_code == 401
        assert (await db_session.scalars(select(Comprobante))).all() == []
        valida = await externo.post(
            url, headers={"x-signature": f"ts={ts},v1={v1}", "x-request-id": "req-9"}
        )
        assert valida.status_code == 200, valida.text
        # Un pago que no es de un cobro de la Suite se audita y se ignora.
        ajeno = mp.informar("otra-cosa", transaction_amount=1.0)
        manif = f"id:{ajeno['id']};request-id:req-9;ts:{ts};"
        firma = hmac.new(b"secreto-mp", manif.encode(), hashlib.sha256).hexdigest()
        desconocido = await externo.post(
            f"/api/v1/pagos/mercadopago/notificaciones?type=payment&data.id={ajeno['id']}",
            headers={"x-signature": f"ts={ts},v1={firma}", "x-request-id": "req-9"},
        )
        assert desconocido.status_code == 200
    assert len((await db_session.scalars(select(Comprobante))).all()) == 1
    assert len(await _eventos(db_session, "PAGO_MP_FIRMA_INVALIDA")) == 2
    assert len(await _eventos(db_session, "PAGO_MP_DESCONOCIDO")) == 1


async def test_permisos(
    app: FastAPI,
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
    mp: MercadoPagoFalso,
    escenario: Escenario,
    db_session: AsyncSession,
) -> None:
    await _pagar(notario, boleta["id"])
    registro = await _pago_mp(db_session, boleta["id"])
    # Un escribano ajeno no ve ni consulta el pago de otro registro.
    ajeno = await make_user(db_session)
    await _escribano(db_session, "Ajeno", ajeno)
    await db_session.commit()
    async with await _client(app) as otro:
        await login(otro, ajeno)
        assert (await _pagar(otro, boleta["id"])).status_code == 404
        sincronizar = await otro.post(f"/api/v1/pagos/mercadopago/{registro.id}/sincronizar")
        assert sincronizar.status_code == 404
    # El registro completo de pagos es de Tesorería.
    assert (await notario.get("/api/v1/pagos/mercadopago")).status_code == 403
    mp.informar(str(registro.id), transaction_amount=Decimal(boleta["total_a_pagar"]))
    await notario.post(f"/api/v1/pagos/mercadopago/{registro.id}/sincronizar")
    lista = (await tesoreria.get("/api/v1/pagos/mercadopago")).json()
    assert lista["total"] == 1
    assert lista["items"][0]["estado"] == "approved"
