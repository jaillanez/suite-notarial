"""Ensayo de corte y reversa cronometrado (DoD de la Fase 10).

Corre sobre `suite_notarial_ensayo` (la crea `make db`), no sobre la base de tests: la reversa
borra y recrea el esquema completo.
"""

import asyncio
import shutil
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.modules.migracion import ensayo


def _url(base: str) -> str:
    raiz, _, _ = base.rpartition("/")
    return f"{raiz}/suite_notarial_ensayo"


def _disponible(url: str) -> bool:
    async def probar() -> bool:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conexion:
                await conexion.execute(text("SELECT 1"))
        except (OSError, SQLAlchemyError):
            return False
        finally:
            await engine.dispose()
        return True

    return asyncio.run(probar())


OWNER = _url(get_settings().migrations_database_url)
APP = _url(str(get_settings().DATABASE_URL))

pytestmark = pytest.mark.skipif(
    shutil.which("pg_dump") is None or not _disponible(OWNER),
    reason="Sin pg_dump o sin la base suite_notarial_ensayo (make db)",
)


async def test_ensayo_de_corte_y_reversa(tmp_path: Path) -> None:
    informe = await ensayo.ensayar(OWNER, APP, tmp_path, registros=12)

    assert informe.resultado == "OK"
    assert informe.reversa_s < ensayo.OBJETIVO_REVERSA_S
    assert informe.conteos_restaurados == informe.conteos_previos
    assert informe.conteos_cargados["historico_boletas"] > 0
    assert (
        informe.conteos_cargados["padron_escribanos"] > informe.conteos_previos["padron_escribanos"]
    )
    pasos = [p["paso"] for p in informe.pasos]
    assert pasos[-3:] == ["carga definitiva", "reversa al respaldo", "verificación posterior"]
    assert (tmp_path / "informe-ensayo.md").is_file()
    assert (tmp_path / "respaldo-previo-a-la-carga.dump").stat().st_size > 0
