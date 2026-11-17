"""Pago de boletas con el botón Supervielle: el pago se registra y queda en revisión; Tesorería
lo confirma. El banco se simula (ningún test llama a su API); los pagos simulados pasan por el
mismo parser que las respuestas reales."""

# ruff: noqa: F811

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.core.config import Environment, Settings, get_settings
from app.modules.pagos import comisiones_spv, supervielle, supervielle_cli, supervielle_service
from app.modules.pagos.catalog import EstadoPagoSPV
from app.modules.pagos.models import Comprobante, PagoSupervielle
from app.modules.parametros import service as parametros
from app.modules.parametros.models import Concepto, Vigencia
from tests.ddjj.conftest import HOY, Escenario, _client, _escribano, staff  # noqa: F401
from tests.iam.factories import make_user
from tests.iam.test_rbac import login
from tests.pagos.conftest import boleta, tesoreria  # noqa: F401 - fixtures compartidas

# La boleta de prueba vence el 23/10 (HOY): el banco exige un vencimiento posterior al día en que
# se publica, así que se paga el día anterior.
AYER = HOY - timedelta(days=1)


def _configurar(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "SUPERVIELLE_USUARIO", "usuario-test")
    monkeypatch.setattr(s, "SUPERVIELLE_CLAVE", SecretStr("clave-test"))
    monkeypatch.setattr(s, "SUPERVIELLE_CLIENT_ID", "client-test")
    monkeypatch.setattr(s, "SUPERVIELLE_CLIENT_SECRET", SecretStr("secret-test"))
    monkeypatch.setattr(s, "SUPERVIELLE_IBM_CLIENT_ID", SecretStr("ibm-test"))
    monkeypatch.setattr(s, "SUPERVIELLE_CONVENIO", 989888)


class BancoFalso:
    """Lo que la Suite le pide al banco y lo que el banco contestaría."""

    def __init__(self) -> None:
        self.publicaciones: list[dict[str, Any]] = []
        self.pagos: dict[str, list[dict[str, Any]]] = {}
        self.caido = False

    async def publicar(self, **datos: Any) -> supervielle.Publicacion:
        if self.caido:
            raise supervielle.SupervielleError("El banco respondió 500 al publicar la deuda.")
        self.publicaciones.append(datos)
        hash_ = str(uuid.uuid4())
        self.pagos[hash_] = []
        return supervielle.Publicacion(hash_, f"https://recaudaciones.test/publicacion/{hash_}")

    def informar(self, hash_: str, **campos: Any) -> dict[str, Any]:
        """Pago tal como lo devuelve la API (JSON)."""
        pago: dict[str, Any] = {
            "id_pago": 5000 + sum(len(p) for p in self.pagos.values()),
            "id_estado_pago": 1,
            "estado_pago": "Aprobado",
            "id_medio_pago": 4,
            "medio_pago": "Qr Modo",
            "importe": None,
            "fecha": "2026-10-22T10:15:00.000",
            **campos,
        }
        self.pagos[hash_].append(pago)
        return pago

    async def pagos_de(self, hash_: str) -> list[supervielle.Pago]:
        if self.caido:
            raise supervielle.SupervielleError("El banco respondió 500.")
        # Mismo camino que una respuesta real: texto JSON leído con Decimal.
        texto = json.dumps(self.pagos.get(hash_, []), default=str)
        return [supervielle.pago_desde(p) for p in json.loads(texto, parse_float=Decimal)]


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> BancoFalso:
    falso = BancoFalso()
    _configurar(monkeypatch)
    monkeypatch.setattr(supervielle_service, "today_local", lambda: AYER)
    monkeypatch.setattr(supervielle, "publicar", falso.publicar)
    monkeypatch.setattr(supervielle, "pagos_de", falso.pagos_de)
    return falso


async def _pagar(cliente: AsyncClient, boleta_id: str) -> Any:
    return await cliente.post(f"/api/v1/pagos/boletas/{boleta_id}/supervielle")


async def _registro(session: AsyncSession, boleta_id: str) -> PagoSupervielle:
    item = await session.scalar(
        select(PagoSupervielle)
        .where(PagoSupervielle.boleta_id == uuid.UUID(boleta_id))
        .order_by(PagoSupervielle.created_at.desc())
    )
    assert item is not None
    await session.refresh(item)
    return item


async def _eventos(session: AsyncSession, tipo: str) -> list[dict[str, Any]]:
    filas = await session.scalars(
        select(AuditSecurityLog.details).where(AuditSecurityLog.event_type == tipo)
    )
    return [d or {} for d in filas.all()]


async def _sincronizar(cliente: AsyncClient, item: PagoSupervielle) -> Any:
    return await cliente.post(f"/api/v1/pagos/supervielle/{item.id}/sincronizar")


# --------------------------------------------------------------------------- cliente de la API


def test_el_pago_se_lee_sin_flotantes_y_con_la_tabla_de_estados() -> None:
    texto = '[{"id_pago": 9, "id_estado_pago": 2, "id_medio_pago": 1, "importe": 341211.07,'
    texto += ' "fecha": "2026-10-22T10:15:00.123"},'
    texto += ' {"id_pago": 10, "id_estado_pago": 99, "medio_pago": "Otro", "importe": 0.1}]'
    acreditado, raro = (supervielle.pago_desde(p) for p in json.loads(texto, parse_float=Decimal))
    assert acreditado.importe == Decimal("341211.07")
    assert acreditado.estado is EstadoPagoSPV.ACREDITADO
    assert acreditado.medio_pago == "Tarjeta de crédito"
    assert acreditado.fecha is not None and acreditado.fecha.date() == date(2026, 10, 22)
    # Un estado que la tabla no tiene no se toma como pagado.
    assert raro.estado is EstadoPagoSPV.PENDIENTE
    assert raro.medio_pago == "Otro"
    with pytest.raises(supervielle.SupervielleError):
        supervielle.pago_desde({"importe": 1})


def test_sin_credenciales_o_convenio_no_esta_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not supervielle.configurado()
    _configurar(monkeypatch)
    assert supervielle.configurado()
    monkeypatch.setattr(get_settings(), "SUPERVIELLE_CONVENIO", None)
    assert not supervielle.configurado()


class _Transporte:
    """API del banco simulada a nivel HTTP, para probar el cliente real."""

    def __init__(self) -> None:
        self.pedidos: list[httpx.Request] = []
        self.tokens = 0
        self.rechazar_token: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.pedidos.append(request)
        if request.url.path.endswith("/token"):
            self.tokens += 1
            return httpx.Response(
                200, json={"access_token": f"tok-{self.tokens}", "expires_in": 300}
            )
        token = request.headers["authorization"].removeprefix("Bearer ")
        if token == self.rechazar_token:
            return httpx.Response(401)
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id_publicacion_cliente": 1000,
                    "hash": "f5d85bfb-b059-40a2-886e-91b49944b0cd",
                    "link_de_pago": " https://recaudaciones.supervielle.com.ar/publicacion/x",
                },
            )
        return httpx.Response(
            200, text='{"pagos": [{"id_pago": 1, "id_estado_pago": 1, "importe": 18000.10}]}'
        )


@pytest.fixture
def transporte(monkeypatch: pytest.MonkeyPatch) -> _Transporte:
    _configurar(monkeypatch)
    simulado = _Transporte()
    original = httpx.AsyncClient

    def cliente(**kwargs: Any) -> httpx.AsyncClient:
        return original(transport=httpx.MockTransport(simulado), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", cliente)
    supervielle._token.olvidar()
    return simulado


async def test_publicar_arma_el_pedido_del_banco(transporte: _Transporte) -> None:
    publicacion = await supervielle.publicar(
        id_publicacion=1000,
        importe=Decimal("341211.07"),
        vence=date(2026, 10, 23),
        nombre="Registro Notarial N° 7",
        descripcion="Boleta N° 1",
        identificadores=["abc"],
    )
    assert publicacion.hash == "f5d85bfb-b059-40a2-886e-91b49944b0cd"
    assert publicacion.link_pago.startswith("https://")
    token, pedido = transporte.pedidos
    assert b"grant_type=password" in token.content
    assert b"scope=boton-pago.publicar" in token.content
    assert token.headers["x-forwarded-host"] == "idpauttst.supervielle.com.ar"
    assert pedido.headers["authorization"] == "Bearer tok-1"
    assert pedido.headers["x-ibm-client-id"] == "ibm-test"
    assert pedido.url.path.endswith("/recaudaciones/v1.0/publicaciones/publicacion")
    # El importe viaja como número exacto, sin pasar por float.
    assert b'"importe1": 341211.07' in pedido.content
    cuerpo = json.loads(pedido.content)
    assert cuerpo["modalidad"] == "Cerrada"
    assert cuerpo["fecha_vencimiento1"] == "2026-10-23"
    assert cuerpo["convenio"] == 989888


async def test_el_token_se_reutiliza_y_se_renueva_ante_un_401(transporte: _Transporte) -> None:
    hash_ = "f5d85bfb-b059-40a2-886e-91b49944b0cd"
    (pago,) = await supervielle.pagos_de(hash_)
    assert pago.importe == Decimal("18000.10")
    await supervielle.pagos_de(hash_)
    assert transporte.tokens == 1
    # El banco deja de aceptar el token: se pide otro y se reintenta una sola vez.
    transporte.rechazar_token = "tok-1"
    await supervielle.pagos_de(hash_)
    assert transporte.tokens == 2
    with pytest.raises(supervielle.SupervielleError, match="inválido"):
        await supervielle.pagos_de("../otra-ruta")


# --------------------------------------------------------------------------- flujo


async def test_sin_configurar_no_se_ofrece(notario: AsyncClient, boleta: dict[str, Any]) -> None:
    estado = await notario.get("/api/v1/pagos/supervielle/estado")
    assert estado.json() == {"habilitado": False}
    assert (await _pagar(notario, boleta["id"])).status_code == 503


async def test_pagar_registra_y_tesoreria_confirma(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
    banco: BancoFalso,
    db_session: AsyncSession,
) -> None:
    estado = await notario.get("/api/v1/pagos/supervielle/estado")
    assert estado.json() == {"habilitado": True}
    respuesta = await _pagar(notario, boleta["id"])
    assert respuesta.status_code == 201, respuesta.text
    item = await _registro(db_session, boleta["id"])
    assert respuesta.json() == {"pago_id": str(item.id), "url_pago": item.link_pago}

    # Se publica el total exacto, con vencimiento en la fecha de pago de la boleta.
    (publicada,) = banco.publicaciones
    assert publicada["importe"] == Decimal(boleta["total_a_pagar"])
    assert publicada["vence"].isoformat() == boleta["fecha_pago"]
    assert str(item.id) in publicada["identificadores"]
    assert publicada["id_publicacion"] == item.id_publicacion
    assert item.estado == "CREADO"

    # Pedir pagar de nuevo reutiliza el mismo link: el banco no permite anular la deuda.
    otra = await _pagar(notario, boleta["id"])
    assert otra.json()["url_pago"] == item.link_pago
    assert len(banco.publicaciones) == 1

    # Sin pagos todavía, «Ya pagué» no cambia nada.
    assert (await _sincronizar(notario, item)).json()["estado"] == "CREADO"

    banco.informar(item.hash, importe=Decimal(boleta["total_a_pagar"]))
    sincronizado = await _sincronizar(notario, item)
    assert sincronizado.status_code == 200, sincronizado.text
    assert sincronizado.json()["estado"] == "APROBADO"
    assert sincronizado.json()["medio_pago"] == "QR MODO"

    # El pago queda en la mesa de Tesorería; la boleta todavía no está pagada.
    comprobante = await db_session.scalar(
        select(Comprobante).where(Comprobante.boleta_id == uuid.UUID(boleta["id"]))
    )
    assert comprobante is not None
    assert comprobante.origen == "SUPERVIELLE"
    assert comprobante.estado == "PENDIENTE_REVISION"
    assert comprobante.archivo is None
    assert comprobante.fecha_transferencia == date(2026, 10, 22)
    detalle = (await notario.get(f"/api/v1/ddjj/boletas/{boleta['id']}")).json()
    assert detalle["estado"] == "PENDIENTE"
    assert (await _pagar(notario, boleta["id"])).status_code == 409
    # Volver a consultar no duplica nada; el paso a acreditado se registra.
    banco.pagos[item.hash][0]["id_estado_pago"] = 2
    assert (await _sincronizar(notario, item)).json()["estado"] == "ACREDITADO"
    assert len((await db_session.scalars(select(Comprobante))).all()) == 1

    visto = (await tesoreria.get(f"/api/v1/pagos/comprobantes/{comprobante.id}")).json()
    assert visto["origen"] == "SUPERVIELLE"
    assert visto["supervielle"]["estado"] == "ACREDITADO"
    assert visto["diferencia"] == "0.00"
    aprobado = await tesoreria.post(
        f"/api/v1/pagos/comprobantes/{comprobante.id}/aprobar",
        json={
            "importe_confirmado": boleta["total_a_pagar"],
            "fecha_acreditacion": "2026-10-23",
            "identificador_extracto": "Rendición Supervielle 23/10",
        },
    )
    assert aprobado.status_code == 200, aprobado.text
    assert (await notario.get(f"/api/v1/ddjj/boletas/{boleta['id']}")).json()["estado"] == "PAGADA"

    assert len(await _eventos(db_session, "PAGO_SPV_INICIADO")) == 1
    acreditados = await _eventos(db_session, "PAGO_SPV_ACREDITADO")
    assert len(acreditados) == 1 and acreditados[0]["importe_coincide"] is True
    assert len(await _eventos(db_session, "PAGO_SPV_ACTUALIZADO")) == 1


async def test_boleta_que_vence_hoy_no_se_publica(
    notario: AsyncClient,
    boleta: dict[str, Any],
    banco: BancoFalso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervielle_service, "today_local", lambda: HOY)
    respuesta = await _pagar(notario, boleta["id"])
    assert respuesta.status_code == 409
    assert "vencen hoy" in respuesta.json()["detail"]
    assert banco.publicaciones == []


async def test_banco_caido(
    notario: AsyncClient, boleta: dict[str, Any], banco: BancoFalso, db_session: AsyncSession
) -> None:
    banco.caido = True
    assert (await _pagar(notario, boleta["id"])).status_code == 503
    assert (await db_session.scalars(select(PagoSupervielle))).all() == []


async def test_pendiente_y_despues_acreditado(
    notario: AsyncClient, boleta: dict[str, Any], banco: BancoFalso, db_session: AsyncSession
) -> None:
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    # Pago en caja del banco: queda pendiente hasta que se acredita.
    pago = banco.informar(item.hash, id_estado_pago=3, id_medio_pago=3, importe=1)
    assert (await _sincronizar(notario, item)).json()["estado"] == "PENDIENTE"
    assert (await db_session.scalars(select(Comprobante))).all() == []
    assert (await _pagar(notario, boleta["id"])).status_code == 409
    pago["id_estado_pago"] = 2
    pago["importe"] = Decimal(boleta["total_a_pagar"])
    assert (await _sincronizar(notario, item)).json()["estado"] == "ACREDITADO"
    assert len((await db_session.scalars(select(Comprobante))).all()) == 1


async def test_importe_distinto_va_a_tesoreria_con_aviso(
    notario: AsyncClient, boleta: dict[str, Any], banco: BancoFalso, db_session: AsyncSession
) -> None:
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    banco.informar(item.hash, importe=10.0)
    await _sincronizar(notario, item)
    comprobante = await db_session.scalar(select(Comprobante))
    assert comprobante is not None
    assert comprobante.importe_declarado == Decimal("10.00")
    assert (await _eventos(db_session, "PAGO_SPV_ACREDITADO"))[0]["importe_coincide"] is False


async def test_sin_importe_informado_no_se_supone_el_total(
    notario: AsyncClient, boleta: dict[str, Any], banco: BancoFalso, db_session: AsyncSession
) -> None:
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    banco.informar(item.hash, importe=None)
    await _sincronizar(notario, item)
    await _sincronizar(notario, item)
    assert (await db_session.scalars(select(Comprobante))).all() == []
    alertas = await _eventos(db_session, "PAGO_SPV_SIN_COMPROBANTE")
    assert len(alertas) == 1 and alertas[0]["motivo"] == "importe no informado"


async def test_un_pago_reversado_no_se_puede_aprobar(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
    banco: BancoFalso,
    db_session: AsyncSession,
) -> None:
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    pago = banco.informar(item.hash, importe=Decimal(boleta["total_a_pagar"]))
    await _sincronizar(notario, item)
    pago["id_estado_pago"] = 4
    await _sincronizar(notario, item)
    comprobante = await db_session.scalar(select(Comprobante))
    assert comprobante is not None
    aprobado = await tesoreria.post(
        f"/api/v1/pagos/comprobantes/{comprobante.id}/aprobar",
        json={"importe_confirmado": boleta["total_a_pagar"], "fecha_acreditacion": "2026-10-23"},
    )
    assert aprobado.status_code == 409
    assert "revirtió" in aprobado.json()["detail"]


async def test_antes_de_aprobar_se_consulta_al_banco(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
    banco: BancoFalso,
    db_session: AsyncSession,
) -> None:
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    pago = banco.informar(item.hash, importe=Decimal(boleta["total_a_pagar"]))
    await _sincronizar(notario, item)
    comprobante = await db_session.scalar(select(Comprobante))
    assert comprobante is not None
    datos = {"importe_confirmado": boleta["total_a_pagar"], "fecha_acreditacion": "2026-10-23"}
    url = f"/api/v1/pagos/comprobantes/{comprobante.id}/aprobar"
    # El banco revirtió el pago y el aviso todavía no llegó: la consulta previa lo detecta.
    pago["id_estado_pago"] = 5
    assert (await tesoreria.post(url, json=datos)).status_code == 409
    # Si el banco no responde, no se aprueba a ciegas.
    pago["id_estado_pago"] = 1
    banco.caido = True
    assert (await tesoreria.post(url, json=datos)).status_code == 503
    assert (await notario.get(f"/api/v1/ddjj/boletas/{boleta['id']}")).json()["estado"] == (
        "PENDIENTE"
    )


def test_convenio_vacio_en_el_env_es_sin_convenio() -> None:
    assert Settings(SUPERVIELLE_CONVENIO="").SUPERVIELLE_CONVENIO is None
    assert Settings(SUPERVIELLE_CONVENIO=" 989888 ").SUPERVIELLE_CONVENIO == 989888


def test_produccion_no_acepta_el_ambiente_de_pruebas_del_banco() -> None:
    base: dict[str, Any] = {
        "ENVIRONMENT": Environment.PRODUCTION,
        "PUBLIC_WEB_URL": "https://suite.cajanotarial-sj.com.ar",
        "SMTP_SECURITY": "tls",
        "MFA_ENFORCED": True,
        "SUPERVIELLE_CONVENIO": 989888,
    }
    with pytest.raises(ValueError, match="ambiente de pruebas del banco"):
        Settings(**base)
    Settings(
        **base,
        SUPERVIELLE_API_URL="https://api.supervielle.com.ar/supervielle/apibank/apibank/x",
        SUPERVIELLE_AUTH_URL="https://api.supervielle.com.ar/supervielle/apibank/auth2/b2b/v2/token",
        SUPERVIELLE_FORWARDED_HOST="idpaut.supervielle.com.ar",
    )


async def test_reversado_queda_como_alerta(
    notario: AsyncClient, boleta: dict[str, Any], banco: BancoFalso, db_session: AsyncSession
) -> None:
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    pago = banco.informar(item.hash, importe=Decimal(boleta["total_a_pagar"]))
    await _sincronizar(notario, item)
    pago["id_estado_pago"] = 4
    assert (await _sincronizar(notario, item)).json()["estado"] == "REVERSADO"
    assert len(await _eventos(db_session, "PAGO_SPV_REVERTIDO")) == 1


async def test_pago_doble_se_avisa_una_vez_sin_otro_comprobante(
    notario: AsyncClient, boleta: dict[str, Any], banco: BancoFalso, db_session: AsyncSession
) -> None:
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    total = Decimal(boleta["total_a_pagar"])
    primero = banco.informar(item.hash, importe=total)
    banco.informar(item.hash, importe=total)
    await _sincronizar(notario, item)
    await _sincronizar(notario, item)
    assert len((await db_session.scalars(select(Comprobante))).all()) == 1
    assert (await _registro(db_session, boleta["id"])).spv_pago_id == str(primero["id_pago"])
    assert len(await _eventos(db_session, "PAGO_SPV_DUPLICADO")) == 1


async def test_aviso_del_banco_sin_sesion(
    app: FastAPI,
    notario: AsyncClient,
    boleta: dict[str, Any],
    banco: BancoFalso,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    banco.informar(item.hash, importe=Decimal(boleta["total_a_pagar"]))
    consultas = 0
    consultar = banco.pagos_de

    async def contar(hash_: str) -> list[supervielle.Pago]:
        nonlocal consultas
        consultas += 1
        return await consultar(hash_)

    monkeypatch.setattr(supervielle, "pagos_de", contar)
    # El banco llama sin cookies ni la cabecera anti-CSRF de la Suite.
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("198.51.100.7", 443)), base_url="https://test"
    ) as externo:
        ajeno = await externo.get(f"/api/v1/pagos/supervielle/aviso/{uuid.uuid4()}")
        assert ajeno.status_code == 400
        assert ajeno.json()["status"] == "error"
        assert (await db_session.scalars(select(Comprobante))).all() == []
        url = f"/api/v1/pagos/supervielle/aviso/{item.hash}"
        valido = await externo.get(url)
        assert valido.status_code == 200, valido.text
        assert valido.json()["status"] == "success"
        # Un aviso repetido enseguida no consulta otra vez al banco: se da por recibido y queda
        # marcado en la base antes de responder (no se pierde aunque se reinicie el proceso).
        assert (await externo.get(url)).status_code == 200
        assert consultas == 1
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("203.0.113.9", 443)), base_url="https://test"
    ) as otro_origen:
        assert (await otro_origen.get(url)).status_code == 200
    assert consultas == 1
    item = await _registro(db_session, boleta["id"])
    assert item.aviso_pendiente_en is not None
    ctx = supervielle_cli.CLI_CONTEXT
    # Dentro de la pausa, el procesamiento programado todavía no consulta.
    assert await supervielle_service.procesar_avisos_pendientes(db_session, ctx) == 0
    # Pasada la pausa, consulta y borra la marca.
    monkeypatch.setattr(supervielle_service, "PAUSA_AVISO", timedelta(0))
    assert await supervielle_service.procesar_avisos_pendientes(db_session, ctx) == 1
    assert consultas == 2
    assert (await _registro(db_session, boleta["id"])).aviso_pendiente_en is None
    # Si el banco no contesta, el aviso no se da por recibido (503: reintenta) y queda pendiente
    # para el procesamiento programado.
    banco.caido = True
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("198.51.100.7", 443)), base_url="https://test"
    ) as externo:
        assert (await externo.get(url)).status_code == 503
    assert (await _registro(db_session, boleta["id"])).aviso_pendiente_en is not None
    assert await supervielle_service.procesar_avisos_pendientes(db_session, ctx) == 0
    assert (await _registro(db_session, boleta["id"])).aviso_pendiente_en is not None
    banco.caido = False
    assert await supervielle_service.procesar_avisos_pendientes(db_session, ctx) == 1
    assert (await _registro(db_session, boleta["id"])).aviso_pendiente_en is None
    assert len((await db_session.scalars(select(Comprobante))).all()) == 1
    # Un hash inventado no deja filas en la auditoría (cualquiera puede llamar a la dirección).
    assert (
        await db_session.scalars(
            select(AuditSecurityLog.id).where(
                AuditSecurityLog.event_type.like("PAGO_SPV_%"),
                AuditSecurityLog.event_type.not_in(("PAGO_SPV_INICIADO", "PAGO_SPV_ACREDITADO")),
            )
        )
    ).all() == []


async def test_permisos(
    app: FastAPI,
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
    banco: BancoFalso,
    escenario: Escenario,
    db_session: AsyncSession,
) -> None:
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    # Un escribano ajeno no ve, no paga ni consulta el pago de otro registro.
    ajeno = await make_user(db_session)
    await _escribano(db_session, "Ajeno", ajeno)
    await db_session.commit()
    async with await _client(app) as otro:
        await login(otro, ajeno)
        assert (await _pagar(otro, boleta["id"])).status_code == 404
        assert (await _sincronizar(otro, item)).status_code == 404
        listado = await otro.get(f"/api/v1/pagos/boletas/{boleta['id']}/supervielle")
        assert listado.status_code == 404
    # El registro completo de pagos es de Tesorería.
    assert (await notario.get("/api/v1/pagos/supervielle")).status_code == 403
    banco.informar(item.hash, importe=Decimal(boleta["total_a_pagar"]))
    await _sincronizar(notario, item)
    lista = (await tesoreria.get("/api/v1/pagos/supervielle")).json()
    assert lista["total"] == 1
    assert lista["items"][0]["estado"] == "APROBADO"
    propios = (await notario.get(f"/api/v1/pagos/boletas/{boleta['id']}/supervielle")).json()
    assert [p["id"] for p in propios] == [str(item.id)]


# --------------------------------------------------------------------------- comisiones


async def _comisiones_aprobadas(session: AsyncSession) -> list[str]:
    """Propone los valores del banco y otra persona los aprueba."""
    autor = await make_user(session, roles=("ROLE_ADMIN",))
    aprobador = await make_user(session, roles=("ROLE_ADMIN",))
    hecho = await comisiones_spv.proponer(session, autor.email, date(2026, 1, 1))
    pendientes = (
        await session.scalars(select(Vigencia.id).where(Vigencia.estado == "PENDIENTE_APROBACION"))
    ).all()
    for vigencia_id in pendientes:
        ctx = comisiones_spv.CLI_CONTEXT
        await parametros.aprobar_vigencia(session, ctx, aprobador, vigencia_id)
    return hecho


async def test_proponer_carga_la_propuesta_del_banco_sin_aprobarla(
    db_session: AsyncSession,
) -> None:
    autor = await make_user(db_session, roles=("ROLE_ADMIN",))
    hecho = await comisiones_spv.proponer(db_session, autor.email, date(2026, 11, 1))
    assert len(hecho) == len(comisiones_spv.PROPUESTA_BANCO)
    efectivo = await db_session.scalar(
        select(Vigencia).join(Concepto).where(Concepto.codigo == "COMISION_SPV_EFECTIVO")
    )
    assert efectivo is not None
    assert efectivo.estado == "PENDIENTE_APROBACION"
    assert efectivo.porcentaje == Decimal("0.25")
    assert efectivo.monto_minimo == Decimal("500.00")
    # Sin aprobar no rige: no se estima nada.
    assert await comisiones_spv.estimar(db_session, Decimal(1000), 3, date(2026, 11, 2)) is None
    # Correrlo de nuevo no duplica: lo ya cargado lo administra la Caja desde Parámetros.
    otra = await comisiones_spv.proponer(db_session, autor.email, date(2026, 11, 1))
    assert all("no se toca" in linea for linea in otra)
    # Quien no puede proponer parámetros, no puede.
    escribano = await make_user(db_session, roles=("ROLE_ESCRIBANO",))
    with pytest.raises(ValueError, match="permiso"):
        await comisiones_spv.proponer(db_session, escribano.email, date(2026, 11, 1))


async def test_estimacion_con_minimo_y_por_medio(db_session: AsyncSession) -> None:
    await _comisiones_aprobadas(db_session)
    fecha = date(2026, 10, 22)
    # Efectivo: 0,4 % del botón + 0,25 % con mínimo de $500.
    chico = await comisiones_spv.estimar(db_session, Decimal("10000.00"), 3, fecha)
    assert chico is not None and chico.comision == Decimal("540.00")
    grande = await comisiones_spv.estimar(db_session, Decimal("1000000.00"), 3, fecha)
    assert grande is not None and grande.comision == Decimal("6500.00")
    # QR MODO: 0,4 % + 0,8 %, redondeo a centavos sin flotantes.
    modo = await comisiones_spv.estimar(db_session, Decimal("341211.07"), 4, fecha)
    assert modo is not None and modo.comision == Decimal("4094.53")
    # Un medio desconocido no se estima.
    assert await comisiones_spv.estimar(db_session, Decimal(1000), 99, fecha) is None


async def test_el_pago_guarda_la_comision_estimada_solo_para_tesoreria(
    notario: AsyncClient,
    tesoreria: AsyncClient,
    boleta: dict[str, Any],
    banco: BancoFalso,
    db_session: AsyncSession,
) -> None:
    await _comisiones_aprobadas(db_session)
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    total = Decimal(boleta["total_a_pagar"])
    banco.informar(item.hash, importe=total, id_medio_pago=2)
    propio = (await _sincronizar(notario, item)).json()
    assert propio["comision_estimada"] is None
    item = await _registro(db_session, boleta["id"])
    esperada = (total * Decimal("0.004")).quantize(Decimal("0.01")) + (
        total * Decimal("0.02")
    ).quantize(Decimal("0.01"))
    assert item.comision_estimada == esperada
    assert item.vigencia_comision_boton_id is not None
    assert item.vigencia_comision_medio_id is not None
    (visto,) = (await tesoreria.get("/api/v1/pagos/supervielle")).json()["items"]
    assert visto["comision_estimada"] == f"{esperada:.2f}"
    assert visto["importe_neto_estimado"] == f"{total - esperada:.2f}"


async def test_la_caja_puede_simular_una_comision(
    db_session: AsyncSession, staff: AsyncClient
) -> None:
    await _comisiones_aprobadas(db_session)
    r = await staff.post(
        "/api/v1/parametros/simulacion",
        json={"concepto_codigo": "COMISION_SPV_EFECTIVO", "fecha": "2026-10-22", "monto": "1000"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["resultado"] == "500.00"


# --------------------------------------------------------------------------- conciliación y consola


async def test_rendicion_pagina_y_lee_sin_flotantes(monkeypatch: pytest.MonkeyPatch) -> None:
    _configurar(monkeypatch)
    supervielle._token.olvidar()
    monkeypatch.setattr(supervielle, "POR_PAGINA", 2)
    paginas = {
        "1": '[{"id_pago": 1, "id_estado_pago": 2, "id_medio_pago": 4, "importe": 100.10,'
        ' "fecha_pago": "2026-10-22T10:00:00.000", "hash_publicacion": "h-1"},'
        ' {"id_pago": 2, "id_estado_pago": 1, "importe": 5, "hash_publicacion": "h-2"}]',
        "2": '{"pagos": [{"id_pago": 3, "id_estado_pago": 1, "importe": 7,'
        ' "hash_publicacion": "h-3"}]}',
    }

    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        assert request.url.path.endswith("/v1.0/rendiciones/pagos")
        assert request.url.params["fecha_desde"] == "2026-10-20"
        return httpx.Response(200, text=paginas[request.url.params["page"]])

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(responder), **kw),
    )
    rendidos = await supervielle.rendicion_pagos(date(2026, 10, 20), date(2026, 10, 22))
    assert [r.hash_publicacion for r in rendidos] == ["h-1", "h-2", "h-3"]
    assert rendidos[0].pago.importe == Decimal("100.10")
    assert rendidos[0].pago.estado is EstadoPagoSPV.ACREDITADO
    assert rendidos[0].pago.fecha is not None


async def test_conciliar_recupera_un_aviso_perdido(
    notario: AsyncClient,
    boleta: dict[str, Any],
    banco: BancoFalso,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    pago = banco.informar(item.hash, importe=Decimal(boleta["total_a_pagar"]))

    async def rendicion(desde: date, hasta: date) -> list[supervielle.PagoRendido]:
        rendido = await banco.pagos_de(item.hash)
        ajeno = supervielle.pago_desde({"id_pago": 77, "id_estado_pago": 1, "importe": 3})
        return [
            supervielle.PagoRendido(item.hash, rendido[0]),
            supervielle.PagoRendido("de-otro-sistema", ajeno),
        ]

    monkeypatch.setattr(supervielle, "rendicion_pagos", rendicion)
    ctx = supervielle_cli.CLI_CONTEXT
    r = await supervielle_service.conciliar(db_session, ctx, AYER - timedelta(days=3), AYER)
    assert r.consultadas == 1
    assert r.actualizadas == [(item.id_publicacion, "CREADO", "APROBADO")]
    assert r.ajenos == [("de-otro-sistema", "77", "3.00")]
    assert r.errores == []
    assert len((await db_session.scalars(select(Comprobante))).all()) == 1
    # Correrla de nuevo no duplica nada; el paso a acreditado se registra.
    pago["id_estado_pago"] = 2
    otra = await supervielle_service.conciliar(db_session, ctx, AYER, AYER)
    assert otra.actualizadas == [(item.id_publicacion, "APROBADO", "ACREDITADO")]
    assert len((await db_session.scalars(select(Comprobante))).all()) == 1


async def test_conciliar_con_el_banco_caido_informa_el_error(
    notario: AsyncClient,
    boleta: dict[str, Any],
    banco: BancoFalso,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _pagar(notario, boleta["id"])

    async def caida(desde: date, hasta: date) -> list[supervielle.PagoRendido]:
        raise supervielle.SupervielleError("El banco respondió 500 al pedir la rendición.")

    banco.caido = True
    monkeypatch.setattr(supervielle, "rendicion_pagos", caida)
    r = await supervielle_service.conciliar(db_session, supervielle_cli.CLI_CONTEXT, AYER, AYER)
    assert len(r.errores) == 2
    assert "rendición" in r.errores[0]


def test_consola_informa_lo_que_falta_sin_mostrar_secretos(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert supervielle_cli.main(["estado"]) == 1
    salida = capsys.readouterr().out
    assert "SUPERVIELLE_CONVENIO" in salida and "PRUEBAS" in salida
    _configurar(monkeypatch)
    assert supervielle_cli.main(["estado"]) == 0
    salida = capsys.readouterr().out
    assert "configuración completa" in salida
    assert "clave-test" not in salida and "secret-test" not in salida


def test_conciliar_sin_configurar_no_falla(capsys: pytest.CaptureFixture[str]) -> None:
    assert supervielle_cli.main(["conciliar"]) == 0
    assert "sin configurar" in capsys.readouterr().out


async def test_probar_publica_solo_en_el_ambiente_de_pruebas(
    transporte: _Transporte,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await supervielle_cli.probar(publicar=True, hash_=None) == 0
    salida = capsys.readouterr().out
    assert "acceso: OK" in salida and "link de pago: https://" in salida
    monkeypatch.setattr(
        get_settings(), "SUPERVIELLE_API_URL", "https://api.supervielle.com.ar/supervielle/x"
    )
    assert await supervielle_cli.probar(publicar=True, hash_=None) == 2


async def test_la_marca_no_se_corre_ni_se_descarta(
    notario: AsyncClient,
    boleta: dict[str, Any],
    banco: BancoFalso,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _pagar(notario, boleta["id"])
    item = await _registro(db_session, boleta["id"])
    # Avisos repetidos: la hora queda en la del más viejo y la generación sube con cada uno.
    await supervielle_service._marcar_pendiente(db_session, item.id)
    primera = (await _registro(db_session, boleta["id"])).aviso_pendiente_en
    await supervielle_service._marcar_pendiente(db_session, item.id)
    item = await _registro(db_session, boleta["id"])
    assert item.aviso_pendiente_en == primera
    assert item.aviso_generacion == 2
    # Si llegó otro aviso mientras se consultaba, la marca se conserva.
    await supervielle_service._limpiar_pendiente(db_session, item.id, 1)
    assert (await _registro(db_session, boleta["id"])).aviso_pendiente_en is not None
    # Una marca de hace más de un día no se descarta: alerta crítica una sola vez.
    item = await _registro(db_session, boleta["id"])
    item.aviso_pendiente_en = datetime.now(UTC) - timedelta(days=2)
    await db_session.commit()
    banco.caido = True
    ctx = supervielle_cli.CLI_CONTEXT
    assert await supervielle_service.procesar_avisos_pendientes(db_session, ctx) == 0
    assert await supervielle_service.procesar_avisos_pendientes(db_session, ctx) == 0
    assert (await _registro(db_session, boleta["id"])).aviso_pendiente_en is not None
    assert len(await _eventos(db_session, "PAGO_SPV_AVISO_DEMORADO")) == 1
    # La conciliación también revisa la publicación con el aviso pendiente.
    banco.caido = False

    async def sin_rendicion(desde: date, hasta: date) -> list[supervielle.PagoRendido]:
        return []

    monkeypatch.setattr(supervielle, "rendicion_pagos", sin_rendicion)
    r = await supervielle_service.conciliar(db_session, ctx, AYER, AYER)
    assert r.consultadas == 1
