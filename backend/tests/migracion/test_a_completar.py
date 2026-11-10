"""Lote sin departamento de los registros ni fecha desde de un cargo: se carga «a completar»."""

import csv
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ddjj import service as ddjj_service
from app.modules.iam.models import User
from app.modules.migracion import carga, formato, homologacion, service
from app.modules.migracion.catalog import Entidad, ModoCorrida, Severidad
from app.modules.migracion.validacion import Existentes, validar
from app.modules.padron.models import Adscripcion, RegistroNotarial


def _vaciar(directorio: Path, entidad: Entidad, columna: str, filas: int | None = None) -> str:
    """Vacía `columna` en las primeras `filas` (todas si None); devuelve el código de la 1.ª."""
    ruta = directorio / f"{entidad.value}.csv"
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f, delimiter=";")
        campos = list(lector.fieldnames or [])
        datos = list(lector)
    for fila in datos[:filas]:
        fila[columna] = ""
    with ruta.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        escritor.writeheader()
        escritor.writerows(datos)
    return datos[0]["codigo_legado"]


def _titular_vigente_primero(directorio: Path) -> None:
    """Deja primero un cargo de titular vigente (el que se vacía)."""
    ruta = directorio / "cargos.csv"
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f, delimiter=";")
        campos = list(lector.fieldnames or [])
        datos = list(lector)
    datos.sort(key=lambda d: not (d["cargo"] == "TITULAR" and not d["fecha_hasta"]))
    with ruta.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        escritor.writeheader()
        escritor.writerows(datos)


def _preparar(directorio: Path) -> str:
    _vaciar(directorio, Entidad.REGISTROS, "departamento")
    _titular_vigente_primero(directorio)
    return _vaciar(directorio, Entidad.CARGOS, "fecha_desde", filas=1)


def test_se_valida_sin_bloquear(lote: Callable[..., Path]) -> None:
    directorio = lote()
    codigo = _preparar(directorio)

    st = validar(formato.leer_lote(directorio), homologacion.cargar(), Existentes())

    assert st.bloqueantes() == 0
    assert all(r.departamento is None for r in st.registros)
    assert next(c for c in st.cargos if c.codigo == codigo).desde is None
    avisos = [o for o in st.observaciones if o.codigo == "FECHA_DESDE_A_COMPLETAR"]
    assert [(o.codigo_legado, o.severidad) for o in avisos] == [(codigo, Severidad.ADVERTENCIA)]


def test_un_departamento_que_viene_se_sigue_validando(lote: Callable[..., Path]) -> None:
    directorio = lote()
    ruta = directorio / "registros.csv"
    texto = ruta.read_text(encoding="utf-8").splitlines()
    campos = texto[0].split(";")
    fila = texto[1].split(";")
    fila[campos.index("departamento")] = "Córdoba"
    ruta.write_text("\n".join([texto[0], ";".join(fila), *texto[2:]]) + "\n", encoding="utf-8")

    st = validar(formato.leer_lote(directorio), homologacion.cargar(), Existentes())

    assert "DEPARTAMENTO_DESCONOCIDO" in {
        o.codigo for o in st.observaciones if o.severidad is Severidad.BLOQUEANTE
    }


async def test_simulacro_cuadra_y_la_carga_queda_a_completar(
    maker: async_sessionmaker[AsyncSession],
    lote: Callable[..., Path],
    operador: User,
    db_session: AsyncSession,
) -> None:
    directorio = lote()
    codigo = _preparar(directorio)

    r = await service.correr(directorio, ModoCorrida.SIMULACRO, operador.email, maker=maker)
    assert r.cuadra is True and r.bloqueantes == 0

    st = validar(formato.leer_lote(directorio), homologacion.cargar(), Existentes())
    async with db_session.begin_nested():
        cargado = await carga.cargar(db_session, st, r.corrida_id, operador.id)
    registros = (await db_session.scalars(select(RegistroNotarial))).all()
    assert registros and all(x.departamento is None for x in registros)
    cargo = await db_session.get(Adscripcion, cargado.ids[Entidad.CARGOS][codigo])
    assert cargo is not None and cargo.fecha_desde is None and cargo.is_current

    # Sin fecha desde, el titular cuenta desde antes de todo: integra el equipo de cualquier
    # período (DDJJ, boletas y reportes lo encuentran).
    equipo = await ddjj_service.cargos_en_periodo(db_session, cargo.registro_id, "2001-01")
    assert cargo.escribano_id in {c.escribano_id for c in equipo}
    # Y no «empieza» en ese período: no se le avisa un mínimo de inicio de cargo.
    avisos = ddjj_service.avisos_de_minimo(equipo, ddjj_service.obligados(equipo), "2001-01")
    assert not any("empieza" in a for a in avisos)
