"""Los comandos de consola corren en un intérprete propio: deben registrar todos los modelos.

Si no, una relación hacia un modelo de otro módulo (p. ej. `Acto.escribano`) falla recién al
consultar, y solo en el servidor (los tests importan todo y lo ocultan).
"""

import subprocess
import sys

import pytest

COMANDOS = [
    "app.modules.iam.cli",
    "app.modules.migracion.cli",
    "app.modules.parametros.historico_caja",
    "app.modules.prestamos.lineas_caja",
    "app.modules.previsional.cargar_puntos",
]

PRUEBA = """
import importlib, sys
importlib.import_module(sys.argv[1])
from app.db.base import Base
propios = len(Base.registry.mappers)
import app.db.models
print(propios, len(Base.registry.mappers))
"""


@pytest.mark.parametrize("modulo", COMANDOS)
def test_el_comando_registra_todos_los_modelos(modulo: str) -> None:
    salida = subprocess.run(  # noqa: S603 - módulos fijos de esta lista
        [sys.executable, "-c", PRUEBA, modulo], capture_output=True, text=True, check=True
    )
    propios, todos = salida.stdout.split()
    assert propios == todos
