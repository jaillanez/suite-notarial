"""Respaldo y reversa de la base de la Suite con las herramientas de PostgreSQL.

Se usa en el corte: respaldo antes de la carga definitiva y, si algo sale mal en la ventana,
reversa al respaldo (manual de corte en Docs/corte-y-reversa.md). Corre con el rol dueño del
esquema (`MIGRATIONS_DATABASE_URL`), sin superusuario: respalda el esquema `public` y restaura
en una sola transacción, de modo que la reversa o se completa o no cambia nada.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.engine import make_url


class ReversaError(RuntimeError):
    pass


def _herramienta(nombre: str) -> str:
    ruta = shutil.which(nombre)
    if ruta is None:
        raise ReversaError(f"No se encontró {nombre}: instalá el cliente de PostgreSQL.")
    return ruta


def _conexion(url: str) -> tuple[list[str], dict[str, str]]:
    """Argumentos de conexión y entorno (la clave va por PGPASSWORD, no en la línea de comando)."""
    datos = make_url(url)
    args = ["-h", datos.host or "localhost", "-p", str(datos.port or 5432)]
    args += ["-U", datos.username or "", "-d", datos.database or ""]
    entorno = {**os.environ, "PGPASSWORD": datos.password or ""}
    return args, entorno


def _correr(comando: list[str], entorno: dict[str, str]) -> None:
    resultado = subprocess.run(comando, env=entorno, capture_output=True, text=True, check=False)  # noqa: S603
    if resultado.returncode != 0:
        raise ReversaError(f"{Path(comando[0]).name} falló: {resultado.stderr.strip()[:2000]}")


def respaldar(url: str, destino: Path) -> int:
    """Respaldo del esquema `public` en formato custom. Devuelve el tamaño en bytes."""
    args, entorno = _conexion(url)
    destino.parent.mkdir(parents=True, exist_ok=True)
    _correr([_herramienta("pg_dump"), *args, "-Fc", "-n", "public", "-f", str(destino)], entorno)
    return destino.stat().st_size


def restaurar(url: str, respaldo: Path) -> None:
    """Vuelve la base al respaldo: borra y recrea los objetos del esquema en una transacción.

    El esquema `public` en sí no se recrea (lo usa la extensión pgcrypto y pertenece al dueño
    desde el bootstrap): se excluye de la lista de restauración.
    """
    if not respaldo.is_file():
        raise ReversaError(f"No existe el respaldo {respaldo}.")
    args, entorno = _conexion(url)
    listado = subprocess.run(  # noqa: S603
        [_herramienta("pg_restore"), "-l", str(respaldo)],
        capture_output=True,
        text=True,
        check=False,
    )
    if listado.returncode != 0:
        raise ReversaError(f"El respaldo no se puede leer: {listado.stderr.strip()[:500]}")
    lineas = [
        ln
        for ln in listado.stdout.splitlines()
        if " SCHEMA - public " not in ln and " SCHEMA public " not in ln
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".lista", delete=False) as lista:
        lista.write("\n".join(lineas) + "\n")
    try:
        _correr(
            [
                _herramienta("pg_restore"),
                *args,
                "--clean",
                "--if-exists",
                "--single-transaction",
                "-L",
                lista.name,
                str(respaldo),
            ],
            entorno,
        )
    finally:
        Path(lista.name).unlink(missing_ok=True)
