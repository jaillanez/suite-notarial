"""Contenido del sitio oficial de la Caja: carga idempotente, auditada y publicada."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditSecurityLog
from app.modules.cms import sitio_oficial
from app.modules.cms.models import Autoridad, Novedad, Pagina
from app.modules.cms.schemas import PaginaIn
from app.modules.iam.models import User
from tests.iam.factories import make_user

PAGINAS = [p.slug for p in sitio_oficial.PAGINAS]


async def _operador(db_session: AsyncSession) -> User:
    return await make_user(db_session, roles=("ROLE_CAJA",))


async def _eventos(db_session: AsyncSession, actor: User) -> list[str]:
    filas = await db_session.scalars(
        select(AuditSecurityLog.event_type).where(AuditSecurityLog.actor_user_id == actor.id)
    )
    return list(filas.all())


def test_textos_completos_y_dentro_del_limite_del_gestor() -> None:
    for pagina in sitio_oficial.PAGINAS:
        # El gestor valida el mismo modelo: lo que se carga se puede volver a editar.
        PaginaIn(grupo=pagina.grupo, titulo=pagina.titulo, contenido=pagina.contenido)
    textos = {p.slug: p.contenido for p in sitio_oficial.PAGINAS}
    ley = textos["ley-de-creacion"]
    assert ley.startswith("LEY N° 7.231")
    assert "## Título VII · Disposiciones generales" in ley
    assert "ARTÍCULO 22.- Comuníquese al Poder Ejecutivo." in ley
    reglamentacion = textos["reglamentacion-de-la-ley"]
    assert reglamentacion.startswith("REGLAMENTACION: LEY 7231")
    assert "## TITULO VI: DISPOSICIONES GENERALES Y TRANSITORIAS" in reglamentacion
    # Los saltos de línea del original (pegado de Word) se unen dentro de cada párrafo.
    assert "La Caja Notarial Mutual de la Provincia de San Juan, Persona Jurídica" in reglamentacion
    aportes = textos["aportes-historicos-y-vigentes"]
    filas = [x for x in aportes.splitlines() if x.startswith("| ") and x[2].isalpha()][1:]
    assert len(filas) == 12
    assert filas[0].startswith("| Octubre 2026 | 30/11/2026 |")
    assert filas[0].endswith("| $ 100.000 |")
    assert filas[-1] == (
        "| Noviembre 2025 | 29/12/2025 | $ 47.346 | $ 1.745.700 | $ 8.200 | $ 30.947 "
        "| $ 71.018 | $ 72.300 |"
    )


async def test_carga_idempotente_auditada_y_publicada(db_session: AsyncSession) -> None:
    actor = await _operador(db_session)
    # Como quedó el servidor de prueba: la ley en borrador con un texto provisorio y el aporte
    # médico de septiembre publicado.
    db_session.add(
        Pagina(
            id=uuid.uuid4(),
            slug="ley-de-creacion",
            grupo="NORMATIVA",
            titulo="Ley de creación de la Caja Notarial de San Juan",
            contenido="Texto de la ley a cargar desde el gestor.",
            orden=1,
            estado="BORRADOR",
            created_by_user_id=actor.id,
        )
    )
    db_session.add(
        Novedad(
            id=uuid.uuid4(),
            slug="aporte-medico-asistencial-septiembre-2026",
            titulo="Aporte médico asistencial",
            seccion="APORTES",
            contenido="Septiembre 2026: $ 97.000.",
            estado="PUBLICADO",
            fecha_publicacion=datetime(2026, 10, 1, 12, tzinfo=UTC),
            autor_user_id=actor.id,
        )
    )
    await db_session.commit()

    primera = await sitio_oficial.cargar(db_session, actor)
    await db_session.commit()

    assert primera.actualizadas == ["ley-de-creacion"]
    assert "ley-de-creacion" in primera.publicadas
    assert primera.archivadas == ["aporte-medico-asistencial-septiembre-2026"]
    paginas = (await db_session.scalars(select(Pagina).order_by(Pagina.slug))).all()
    assert sorted(p.slug for p in paginas) == sorted(PAGINAS)
    assert all(p.estado == "PUBLICADO" for p in paginas)
    novedades = {n.slug: n for n in (await db_session.scalars(select(Novedad))).all()}
    assert novedades["aporte-medico-asistencial-octubre-2026"].estado == "PUBLICADO"
    assert novedades["aporte-medico-asistencial-septiembre-2026"].estado == "ARCHIVADO"
    assert await db_session.scalar(select(func.count()).select_from(Autoridad)) == 9
    eventos = await _eventos(db_session, actor)
    assert eventos.count("CMS_PAGINA_CREADA") == 3
    assert eventos.count("CMS_PAGINA_ACTUALIZADA") == 1
    assert eventos.count("CMS_AUTORIDAD_CREADA") == 9

    segunda = await sitio_oficial.cargar(db_session, actor)
    await db_session.commit()

    assert segunda.creadas == segunda.actualizadas == segunda.publicadas == []
    assert segunda.archivadas == []
    assert len(segunda.sin_cambios) == len(PAGINAS) + len(sitio_oficial.NOVEDADES) + 9
    assert len(await _eventos(db_session, actor)) == len(eventos)


async def test_operador_sin_permiso_o_inexistente(db_session: AsyncSession) -> None:
    escribano = await make_user(db_session)
    with pytest.raises(sitio_oficial.SitioOficialError, match="cms:publish"):
        await sitio_oficial.operador(db_session, escribano.email)
    with pytest.raises(sitio_oficial.SitioOficialError, match="No hay un usuario activo"):
        await sitio_oficial.operador(db_session, "nadie@ejemplo.test")


def test_consola_informa_el_resumen(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def falso(email: str, *, simular: bool) -> sitio_oficial.Resumen:
        assert (email, simular) == ("caja@ejemplo.test", True)
        return sitio_oficial.Resumen(creadas=["ley-de-creacion"], archivadas=["aporte-x"])

    monkeypatch.setattr(sitio_oficial, "ejecutar", falso)
    assert sitio_oficial.main(["--operador", "caja@ejemplo.test", "--simular"]) == 0
    salida = capsys.readouterr().out
    assert "SIMULACIÓN" in salida
    assert "Creadas: 1 (ley-de-creacion)" in salida
    assert "Archivadas: 1 (aporte-x)" in salida
