"""Teléfono y correo de los registros desde el sitio web anterior (volcado sintético)."""

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditEvent, AuditSecurityLog
from app.modules.migracion import contacto_registros as contacto
from app.modules.migracion.service import MigracionError
from tests.iam.factories import make_user
from tests.padron.conftest import Factory

VOLCADO = """-- volcado sintético
CREATE TABLE `registro_notarial` (`id` int(11) NOT NULL);
INSERT INTO `registro_notarial` (`id`, `domicilio`, `telefono`, `email`, `numero`, `estado`) VALUES
(1, 'Calle 1', '4200001', 'Uno@Ejemplo.com.ar', 901, 0),
(2, 'Calle 2', '--', '--', 902, 0),
(3, 'Calle 3', '4200003', 'tres @ejemplo.com.ar', 903, 0),
(4, 'Calle 4', ' 4200004 - 4200005 ', '', 904, 0),
(5, 'Calle 5', '4200006', 'cinco@ejemplo.com.ar', 905, 0);
"""


def test_extraer_descarta_sin_dato_y_correos_invalidos() -> None:
    e = contacto.extraer(VOLCADO)
    assert e.contactos == [
        contacto.Contacto(901, "4200001", "uno@ejemplo.com.ar"),
        contacto.Contacto(903, "4200003", None),
        contacto.Contacto(904, "4200004 - 4200005", None),
        contacto.Contacto(905, "4200006", "cinco@ejemplo.com.ar"),
    ]
    assert e.descartados == [(903, "correo inválido «tres @ejemplo.com.ar»")]


def test_extraer_rechaza_registros_repetidos() -> None:
    repetido = VOLCADO.replace(
        "(5, 'Calle 5', '4200006', 'cinco@ejemplo.com.ar', 905", "(5, 'X', '1', '', 901"
    )
    with pytest.raises(contacto.ContactoInvalidoError, match="dos veces"):
        contacto.extraer(repetido)


def test_csv_ida_y_vuelta(tmp_path: Path) -> None:
    contactos = contacto.extraer(VOLCADO).contactos
    archivo = tmp_path / "contacto.csv"
    contacto.escribir_csv(contactos, archivo)
    assert contacto.leer_csv(archivo) == contactos


def test_cli_extraer_no_sobrescribe(tmp_path: Path) -> None:
    volcado = tmp_path / "volcado.sql"
    volcado.write_text(VOLCADO, encoding="utf-8")
    salida = tmp_path / "contacto.csv"
    assert contacto.main(["extraer", "--volcado", str(volcado), "--salida", str(salida)]) == 0
    assert len(contacto.leer_csv(salida)) == 4
    assert contacto.main(["extraer", "--volcado", str(volcado), "--salida", str(salida)]) == 2


async def _get(caja: AsyncClient, registro: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = (await caja.get(f"/api/v1/padron/registros/{registro['id']}")).json()
    return body


async def test_cargar_completa_solo_lo_vacio_y_audita(
    caja: AsyncClient, registro: Factory, db_session: AsyncSession
) -> None:
    operador = await make_user(db_session, roles=("ROLE_ADMIN",))
    vacio = await registro(901)
    corregido = await registro(903, telefono="4299999")
    cerrado = await registro(905)
    cierre = await caja.post(
        f"/api/v1/padron/registros/{cerrado['id']}/cierre", json={"motivo": "Cierre de prueba"}
    )
    assert cierre.status_code == 200, cierre.text
    contactos = contacto.extraer(VOLCADO).contactos

    previa = await contacto.cargar(db_session, operador.email, contactos, aplicar=False)
    assert previa.completados == [901]
    assert (await _get(caja, vacio))["telefono"] is None  # sin --aplicar no guarda

    r = await contacto.cargar(db_session, operador.email, contactos, aplicar=True)
    assert r.completados == [901]
    assert r.sin_cambios == [903]
    assert r.diferencias == [(903, "telefono", "4299999", "4200003")]
    assert r.sin_registro == [904]
    assert r.cerrados == [905]

    datos = await _get(caja, vacio)
    assert (datos["telefono"], datos["email"]) == ("4200001", "uno@ejemplo.com.ar")
    assert (await _get(caja, corregido))["telefono"] == "4299999"  # lo de la Suite no se pisa
    log = await db_session.scalar(
        select(AuditSecurityLog).where(
            AuditSecurityLog.event_type == AuditEvent.PADRON_REGISTRO_UPDATED.value,
            AuditSecurityLog.actor_user_id == operador.id,
        )
    )
    assert log is not None
    assert log.old_value is not None and log.old_value["telefono"] is None
    assert log.new_value is not None and log.new_value["email"] == "uno@ejemplo.com.ar"

    otra = await contacto.cargar(db_session, operador.email, contactos, aplicar=True)
    assert otra.completados == []  # idempotente


async def test_cargar_exige_operador_de_migracion(
    registro: Factory, db_session: AsyncSession
) -> None:
    await registro(901)
    escribano = await make_user(db_session, roles=("ROLE_ESCRIBANO",))
    with pytest.raises(MigracionError, match="migracion:ejecutar"):
        await contacto.cargar(
            db_session, escribano.email, contacto.extraer(VOLCADO).contactos, aplicar=True
        )
