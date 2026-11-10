"""Contenido del sitio oficial de la Caja (https://www.cajanotarial-sj.com.ar/, 10/11/2026).

Trae al sitio nuevo lo que hoy publica el sitio oficial: Quiénes somos, Ley de creación,
Reglamentación de la ley, Aportes previsionales y médicos históricos y vigentes (la tabla de
aportes históricos, que el sitio oficial muestra como imagen, va transcripta), las novedades y
las autoridades. Los textos están en `contenido_oficial/`, tal cual el sitio oficial salvo los
saltos de línea y los títulos (`## `), y el vademécum de aportes, pasado de mayúsculas a texto.

Los estados contables del sitio oficial están detrás del acceso de afiliados: no se traen.

Carga (idempotente, por enlace; nunca borra):

    python -m app.modules.cms.sitio_oficial --operador EMAIL [--simular]

Crea lo que falta, actualiza lo que difiere y publica. Un aporte médico de un mes anterior que
siga publicado se archiva. Cada cambio queda en la auditoría a nombre del operador.
"""

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Registra todos los modelos: corriendo solo, SQLAlchemy no resolvería las relaciones.
import app.db.models  # noqa: F401
from app.common.audit import AuditEvent, RequestContext, Severity, record_audit
from app.core.db import get_engine, get_sessionmaker
from app.modules.cms.catalog import EstadoPublicacion, GrupoPagina, SeccionNovedad
from app.modules.cms.models import Autoridad, Novedad, Pagina
from app.modules.cms.service import AUTORIDAD_CAMPOS, NOVEDAD_CAMPOS, _valores
from app.modules.cms.sitio import PAGINA_CAMPOS
from app.modules.iam.catalog import Perm
from app.modules.iam.models import User

CONSOLA = RequestContext(
    ip_address=None, user_agent="cli", correlation_id=None, path="cli:cms.sitio_oficial"
)
ORIGEN = "Sitio oficial cajanotarial-sj.com.ar (10/11/2026)"
CONTENIDO = Path(__file__).with_name("contenido_oficial")
PUBLICADO = EstadoPublicacion.PUBLICADO.value
ARCHIVADO = EstadoPublicacion.ARCHIVADO.value
APORTE_MEDICO = "aporte-medico-asistencial-"


@dataclass(frozen=True)
class PaginaOficial:
    slug: str
    grupo: GrupoPagina
    titulo: str
    orden: int

    @property
    def contenido(self) -> str:
        return (CONTENIDO / f"{self.slug}.txt").read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class NovedadOficial:
    slug: str
    seccion: SeccionNovedad
    titulo: str
    resumen: str
    contenido: str
    fecha: datetime


PAGINAS = (
    PaginaOficial("quienes-somos", GrupoPagina.CAJA, "Quiénes somos", 1),
    PaginaOficial(
        "ley-de-creacion",
        GrupoPagina.NORMATIVA,
        "Ley de creación de la Caja Notarial de San Juan",
        1,
    ),
    PaginaOficial("reglamentacion-de-la-ley", GrupoPagina.NORMATIVA, "Reglamentación de la ley", 2),
    PaginaOficial(
        "aportes-historicos-y-vigentes",
        GrupoPagina.NORMATIVA,
        "Aportes previsionales y médicos históricos y vigentes",
        3,
    ),
)

NOVEDADES = (
    NovedadOficial(
        "aporte-medico-asistencial-octubre-2026",
        SeccionNovedad.APORTES,
        "Aporte médico asistencial",
        "Octubre 2026: $ 100.000. Para meses anteriores, consultar Normativa / Aportes.",
        "Octubre 2026: $ 100.000.\n\n"
        "Para meses anteriores consultar en nuestra página web, accediendo a Normativa / "
        "Aportes previsionales y médicos históricos y vigentes.",
        datetime(2026, 11, 1, 12, tzinfo=UTC),
    ),
    NovedadOficial(
        "nuevas-autoridades-vigentes",
        SeccionNovedad.INSTITUCIONAL,
        "Nuevas autoridades vigentes",
        "Asamblea ordinaria del 16/12/2025.",
        "Julio Alejandro Lloveras (Presidente), María Ingrid Luluaga (Vicepresidente), "
        "Liliana Selva Jofré (Tesorera) y Guillermo Ned Aguilar (Secretario).\n\n"
        "Según Asamblea General Ordinaria del 16 de diciembre de 2025.",
        datetime(2025, 12, 17, 12, tzinfo=UTC),
    ),
    NovedadOficial(
        "renovacion-de-nuestra-pagina-web",
        SeccionNovedad.COMUNICADOS,
        "Renovación de nuestra página web",
        "Ya pueden presentar las DDJJ de aportes por la web, ingresando a Acceso afiliados.",
        "Estimados notarios:\n\n"
        "Recuerden que ya pueden realizar la presentación de las DDJJ de aportes por nuestra "
        "página web, ingresando a Acceso afiliados.\n\n"
        "Se prorrogó la obligatoriedad de la presentación por la web, pudiendo continuar con el "
        "sistema anterior, presentación en papel por nuestras oficinas, hasta nuevo aviso.\n\n"
        "Estamos a disposición para asistirlos, tanto en crear usuario y contraseña como en la "
        "carga de las DDJJ.",
        datetime(2025, 11, 3, 12, tzinfo=UTC),
    ),
)

# Según Asamblea General Ordinaria del 16 de diciembre de 2025.
MANDATO_DESDE = date(2025, 12, 16)
AUTORIDADES: tuple[tuple[str, str, int], ...] = (
    ("Presidente", "Lloveras, Julio Alejandro", 1),
    ("Vicepresidente", "Luluaga, María Ingrid", 2),
    ("Secretario", "Aguilar, Guillermo Ned", 3),
    ("Tesorera", "Jofré, Liliana Selva", 4),
    ("Suplente", "Barros, Fernando", 5),
    ("Suplente", "Barroso, Mariana", 6),
    ("Suplente", "Fagale, Ana Paula", 7),
    ("Síndico titular", "Pérez Olivera, Nicolás", 8),
    ("Síndico suplente", "Alvea, Flavia Vanesa", 9),
)


class SitioOficialError(RuntimeError):
    pass


@dataclass
class Resumen:
    creadas: list[str] = field(default_factory=list)
    actualizadas: list[str] = field(default_factory=list)
    publicadas: list[str] = field(default_factory=list)
    sin_cambios: list[str] = field(default_factory=list)
    archivadas: list[str] = field(default_factory=list)


async def operador(session: AsyncSession, email: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        raise SitioOficialError(f"No hay un usuario activo con el correo {email}.")
    if Perm.CMS_PUBLISH.value not in user.permission_codes:
        raise SitioOficialError("El operador no tiene el permiso cms:publish.")
    return user


def _publicar(session: AsyncSession, item: Pagina | Novedad, actor: User, resumen: Resumen) -> None:
    """Publica lo que no está publicado (un archivado también vuelve a publicarse)."""
    anterior = item.estado
    if anterior == PUBLICADO:
        return
    item.estado = PUBLICADO
    if isinstance(item, Novedad):
        if item.fecha_publicacion is None:
            item.fecha_publicacion = datetime.now(UTC)
        evento, clave = AuditEvent.CMS_NOVEDAD_ESTADO, "novedad_id"
    else:
        evento, clave = AuditEvent.CMS_PAGINA_ESTADO, "pagina_id"
    record_audit(
        session,
        CONSOLA,
        evento,
        severity=Severity.WARNING,
        actor_user_id=actor.id,
        old_value={"estado": anterior},
        new_value={"estado": PUBLICADO},
        details={clave: str(item.id), "slug": item.slug, "origen": ORIGEN},
    )
    resumen.publicadas.append(item.slug)


async def _paginas(session: AsyncSession, actor: User, resumen: Resumen) -> None:
    for data in PAGINAS:
        nuevos = {
            "slug": data.slug,
            "grupo": data.grupo.value,
            "titulo": data.titulo,
            "contenido": data.contenido,
            "orden": data.orden,
        }
        item = await session.scalar(
            select(Pagina).where(Pagina.slug == data.slug).with_for_update()
        )
        if item is None:
            item = Pagina(id=uuid.uuid4(), **nuevos, estado=EstadoPublicacion.BORRADOR.value)
            item.created_by_user_id = actor.id
            session.add(item)
            record_audit(
                session,
                CONSOLA,
                AuditEvent.CMS_PAGINA_CREADA,
                actor_user_id=actor.id,
                new_value=_valores(item, PAGINA_CAMPOS),
                details={"pagina_id": str(item.id), "origen": ORIGEN},
            )
            resumen.creadas.append(data.slug)
        else:
            antes = _valores(item, PAGINA_CAMPOS)
            for campo, valor in nuevos.items():
                setattr(item, campo, valor)
            despues = _valores(item, PAGINA_CAMPOS)
            cambios = [c for c in PAGINA_CAMPOS if antes[c] != despues[c]]
            if cambios:
                record_audit(
                    session,
                    CONSOLA,
                    AuditEvent.CMS_PAGINA_ACTUALIZADA,
                    actor_user_id=actor.id,
                    old_value={c: antes[c] for c in cambios},
                    new_value={c: despues[c] for c in cambios},
                    details={"pagina_id": str(item.id), "estado": item.estado, "origen": ORIGEN},
                )
                resumen.actualizadas.append(data.slug)
            elif item.estado == PUBLICADO:
                resumen.sin_cambios.append(data.slug)
        _publicar(session, item, actor, resumen)


async def _novedades(session: AsyncSession, actor: User, resumen: Resumen) -> None:
    for data in NOVEDADES:
        nuevos = {
            "slug": data.slug,
            "titulo": data.titulo,
            "resumen": data.resumen,
            "seccion": data.seccion.value,
            "contenido": data.contenido,
        }
        item = await session.scalar(
            select(Novedad).where(Novedad.slug == data.slug).with_for_update()
        )
        if item is None:
            item = Novedad(
                id=uuid.uuid4(),
                **nuevos,
                estado=EstadoPublicacion.BORRADOR.value,
                fecha_publicacion=data.fecha,
                autor_user_id=actor.id,
            )
            session.add(item)
            record_audit(
                session,
                CONSOLA,
                AuditEvent.CMS_NOVEDAD_CREADA,
                actor_user_id=actor.id,
                new_value=_valores(item, NOVEDAD_CAMPOS),
                details={"novedad_id": str(item.id), "origen": ORIGEN},
            )
            resumen.creadas.append(data.slug)
        else:
            antes = _valores(item, NOVEDAD_CAMPOS)
            for campo, valor in nuevos.items():
                setattr(item, campo, valor)
            despues = _valores(item, NOVEDAD_CAMPOS)
            cambios = [c for c in NOVEDAD_CAMPOS if antes[c] != despues[c]]
            if cambios:
                record_audit(
                    session,
                    CONSOLA,
                    AuditEvent.CMS_NOVEDAD_ACTUALIZADA,
                    actor_user_id=actor.id,
                    old_value={c: antes[c] for c in cambios},
                    new_value={c: despues[c] for c in cambios},
                    details={"novedad_id": str(item.id), "estado": item.estado, "origen": ORIGEN},
                )
                resumen.actualizadas.append(data.slug)
            elif item.estado == PUBLICADO:
                resumen.sin_cambios.append(data.slug)
        _publicar(session, item, actor, resumen)

    # El sitio oficial muestra solo el aporte médico del último mes: los anteriores se archivan.
    vigente = next(n.slug for n in NOVEDADES if n.slug.startswith(APORTE_MEDICO))
    anteriores = await session.scalars(
        select(Novedad)
        .where(
            Novedad.slug.startswith(APORTE_MEDICO),
            Novedad.slug != vigente,
            Novedad.estado == PUBLICADO,
        )
        .order_by(Novedad.slug)
        .with_for_update()
    )
    for item in anteriores.all():
        item.estado = ARCHIVADO
        record_audit(
            session,
            CONSOLA,
            AuditEvent.CMS_NOVEDAD_ESTADO,
            severity=Severity.WARNING,
            actor_user_id=actor.id,
            old_value={"estado": PUBLICADO},
            new_value={"estado": ARCHIVADO},
            details={"novedad_id": str(item.id), "slug": item.slug, "origen": ORIGEN},
        )
        resumen.archivadas.append(item.slug)


async def _autoridades(session: AsyncSession, actor: User, resumen: Resumen) -> None:
    """Crea las autoridades que falten (por cargo y nombre); no toca las que ya están."""
    existentes = {
        (a.cargo, a.nombre)
        for a in await session.scalars(select(Autoridad).where(Autoridad.is_active.is_(True)))
    }
    for cargo, nombre, orden in AUTORIDADES:
        if (cargo, nombre) in existentes:
            resumen.sin_cambios.append(f"{cargo}: {nombre}")
            continue
        item = Autoridad(
            id=uuid.uuid4(),
            cargo=cargo,
            nombre=nombre,
            orden=orden,
            mandato_desde=MANDATO_DESDE,
            created_by_user_id=actor.id,
        )
        session.add(item)
        record_audit(
            session,
            CONSOLA,
            AuditEvent.CMS_AUTORIDAD_CREADA,
            actor_user_id=actor.id,
            new_value=_valores(item, AUTORIDAD_CAMPOS[:-1]),
            details={"autoridad_id": str(item.id), "origen": ORIGEN},
        )
        resumen.creadas.append(f"{cargo}: {nombre}")


async def cargar(session: AsyncSession, actor: User) -> Resumen:
    """Deja el sitio con el contenido del sitio oficial. No confirma: lo hace quien llama."""
    resumen = Resumen()
    await _paginas(session, actor, resumen)
    await _novedades(session, actor, resumen)
    await _autoridades(session, actor, resumen)
    await session.flush()
    return resumen


def _out(mensaje: str) -> None:
    sys.stdout.write(mensaje + "\n")


def _err(mensaje: str) -> None:
    sys.stderr.write(mensaje + "\n")


def _informar(resumen: Resumen, *, simular: bool) -> None:
    _out(("SIMULACIÓN (no se guardó nada) · " if simular else "") + ORIGEN)
    for titulo, items in (
        ("Creadas", resumen.creadas),
        ("Actualizadas", resumen.actualizadas),
        ("Publicadas", resumen.publicadas),
        ("Archivadas", resumen.archivadas),
        ("Sin cambios", resumen.sin_cambios),
    ):
        _out(f"{titulo}: {len(items)}" + (f" ({', '.join(items)})" if items else ""))


async def ejecutar(email: str, *, simular: bool) -> Resumen:
    async with get_sessionmaker()() as session:
        actor = await operador(session, email)
        resumen = await cargar(session, actor)
        if simular:
            await session.rollback()
        else:
            await session.commit()
        return resumen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sitio_oficial", description="Trae el contenido del sitio oficial de la Caja"
    )
    parser.add_argument("--operador", required=True, help="Correo de un usuario con cms:publish")
    parser.add_argument(
        "--simular", action="store_true", help="Muestra qué cambiaría, sin guardar nada"
    )
    args = parser.parse_args(argv)

    async def correr() -> int:
        try:
            resumen = await ejecutar(args.operador, simular=args.simular)
        except SitioOficialError as exc:
            _err(str(exc))
            return 2
        finally:
            await get_engine().dispose()
        _informar(resumen, simular=args.simular)
        return 0

    return asyncio.run(correr())


if __name__ == "__main__":
    raise SystemExit(main())
