"""Contenido de desarrollo del sitio, tomado del sitio público actual de la Caja
(https://www.cajanotarial-sj.com.ar/, octubre de 2026) para ver la portada armada.

Solo para `make seed-dev`: en cada entorno real el contenido lo carga la Caja desde el gestor.
Las notas y páginas se crean una sola vez (se reconocen por su enlace).
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cms.catalog import EstadoPublicacion, GrupoPagina, SeccionNovedad
from app.modules.cms.models import Autoridad, Novedad, Pagina

PUBLICADO = EstadoPublicacion.PUBLICADO.value
BORRADOR = EstadoPublicacion.BORRADOR.value

NOVEDADES: list[tuple[str, SeccionNovedad, str, str, str, datetime]] = [
    (
        "aporte-medico-asistencial-septiembre-2026",
        SeccionNovedad.APORTES,
        "Aporte médico asistencial",
        "Septiembre 2026: $ 97.000. Para meses anteriores, consultar Normativa / Aportes.",
        "Septiembre 2026: $ 97.000.\n\n"
        "Para meses anteriores consultar en nuestra página web, accediendo a Normativa / "
        "Aportes previsionales y médicos históricos y vigentes.",
        datetime(2026, 10, 1, 12, tzinfo=UTC),
    ),
    (
        "nuevas-autoridades-vigentes",
        SeccionNovedad.INSTITUCIONAL,
        "Nuevas autoridades vigentes",
        "Asamblea ordinaria del 16/12/2025.",
        "Julio Alejandro Lloveras (Presidente), María Ingrid Luluaga (Vicepresidente), "
        "Liliana Selva Jofré (Tesorera) y Guillermo Ned Aguilar (Secretario).\n\n"
        "Según Asamblea General Ordinaria del 16 de diciembre de 2025.",
        datetime(2025, 12, 17, 12, tzinfo=UTC),
    ),
    (
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
]

QUIENES_SOMOS = (
    "La Caja Notarial de San Juan, persona jurídica de derecho público no estatal, sin fines de "
    "lucro, fue creada por la Ley 6.043 del año 1990 con el nombre de Caja Notarial Mutual de la "
    "Provincia de San Juan.\n\n"
    "La Ley 7.231, que modifica el régimen vigente, fue promulgada en el año 2002 y tiene por "
    "objeto otorgar las siguientes prestaciones:\n\n"
    "Jubilación ordinaria.\n"
    "Jubilación extraordinaria por incapacidad.\n"
    "Pensión derivada o directa.\n"
    "Subsidio por fallecimiento o por incapacidad.\n"
    "Seguros de sepelio.\n"
    "Préstamos reintegrables."
)

APORTES = (
    "Aportes previsionales vigentes desde junio de 2026, aprobados por la Asamblea "
    "Extraordinaria celebrada el 19/05/2026.\n\n"
    "a) Aporte previsional mensual mínimo, desde junio de 2026: $ 85.932.\n"
    "b) Aporte variable por escrituras realizadas desde el 1 de junio de 2026: el 0,40 % del "
    "valor de la escritura, con un aporte mínimo de $ 57.289,00 y un aporte máximo de "
    "$ 3.482.672,00.\n"
    "c) Aportes fijos por actas y poderes: desde junio de 2026, $ 9.922,00.\n"
    "d) Aportes fijos por otros actos: desde junio de 2026, $ 37.446,00.\n\n"
    "Pluralidad de actos: cuando en una escritura hay más de un acto (gratuitos u onerosos) y "
    "solo dos partes, solo corresponde aportar por uno de ellos, el de mayor valor.\n\n"
    "Pluralidad de actos y de partes: cuando en una escritura hay más de un acto oneroso, con "
    "distintas partes intervinientes, corresponde aportar por cada uno de esos actos."
)

PAGINAS: list[tuple[str, GrupoPagina, str, str, int, str]] = [
    ("quienes-somos", GrupoPagina.CAJA, "Quiénes somos", QUIENES_SOMOS, 1, PUBLICADO),
    (
        "ley-de-creacion",
        GrupoPagina.NORMATIVA,
        "Ley de creación de la Caja Notarial de San Juan",
        "Texto de la ley a cargar desde el gestor.",
        1,
        BORRADOR,
    ),
    (
        "reglamentacion-de-la-ley",
        GrupoPagina.NORMATIVA,
        "Reglamentación de la ley",
        "Texto de la reglamentación a cargar desde el gestor.",
        2,
        BORRADOR,
    ),
    (
        "aportes-historicos-y-vigentes",
        GrupoPagina.NORMATIVA,
        "Aportes previsionales y médicos históricos y vigentes",
        APORTES,
        3,
        PUBLICADO,
    ),
]

AUTORIDADES: list[tuple[str, str, int]] = [
    ("Presidente", "Lloveras, Julio Alejandro", 1),
    ("Vicepresidente", "Luluaga, María Ingrid", 2),
    ("Secretario", "Aguilar, Guillermo Ned", 3),
    ("Tesorera", "Jofré, Liliana Selva", 4),
    ("Suplente", "Barros, Fernando", 5),
    ("Suplente", "Barroso, Mariana", 6),
    ("Suplente", "Fagale, Ana Paula", 7),
    ("Síndico titular", "Pérez Olivera, Nicolás", 8),
    ("Síndico suplente", "Alvea, Flavia Vanesa", 9),
]


async def seed_sitio(session: AsyncSession, autor_id: uuid.UUID) -> int:
    creados = 0
    for slug, seccion, titulo, resumen, contenido, fecha in NOVEDADES:
        if await session.scalar(select(Novedad.id).where(Novedad.slug == slug)):
            continue
        session.add(
            Novedad(
                slug=slug,
                titulo=titulo,
                resumen=resumen,
                seccion=seccion.value,
                contenido=contenido,
                estado=PUBLICADO,
                fecha_publicacion=fecha,
                autor_user_id=autor_id,
            )
        )
        creados += 1
    for slug, grupo, titulo, contenido, orden, estado in PAGINAS:
        if await session.scalar(select(Pagina.id).where(Pagina.slug == slug)):
            continue
        session.add(
            Pagina(
                slug=slug,
                grupo=grupo.value,
                titulo=titulo,
                contenido=contenido,
                orden=orden,
                estado=estado,
                created_by_user_id=autor_id,
            )
        )
        creados += 1
    if not await session.scalar(select(Autoridad.id).limit(1)):
        for cargo, nombre, orden in AUTORIDADES:
            session.add(
                Autoridad(
                    cargo=cargo,
                    nombre=nombre,
                    orden=orden,
                    mandato_desde=date(2025, 12, 16),
                    created_by_user_id=autor_id,
                )
            )
            creados += 1
    await session.commit()
    return creados
