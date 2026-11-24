"""Teléfono y correo de los registros, tomados del sitio web anterior (volcado MySQL).

La carga definitiva ya se hizo (una sola por base) y las planillas de la Caja no traen el
contacto de los registros; el sitio web anterior sí (`registro_notarial.telefono` y `.email`).
Son dos pasos para que el volcado, que tiene datos sensibles, no salga del equipo de trabajo:

- `extraer` (en el equipo): lee el volcado sin ejecutar su SQL y escribe un CSV con solo
  `numero_registro;telefono;email`. «--» o vacío = sin dato. Un correo inválido no se toma (se
  informa para que la Caja lo corrija); no se adivina la corrección.
- `cargar` (en el servidor): completa cada registro de la Suite por su número, solo en los campos
  vacíos: lo que ya se cargó o corrigió en la Suite no se pisa (se informa la diferencia). Sin
  `--aplicar` solo informa. Cada registro completado queda auditado (PADRON_REGISTRO_UPDATED,
  valor previo y nuevo) a nombre del operador, con origen `cli:migracion:contacto_registros`.

python -m app.modules.migracion.contacto_registros extraer --volcado SQL --salida CSV
python -m app.modules.migracion.contacto_registros cargar --archivo CSV --operador EMAIL [--aplicar]
"""

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import RequestContext
from app.modules.migracion.extractor_web import leer_volcado
from app.modules.padron.models import RegistroNotarial
from app.modules.padron.schemas import RegistroUpdate

COLUMNAS = ("numero_registro", "telefono", "email")
SIN_DATO = {"", "-", "--", "---"}
MAX_TELEFONO = 50
ORIGEN = RequestContext(
    ip_address=None, user_agent="cli", correlation_id=None, path="cli:migracion:contacto_registros"
)
_EMAIL: TypeAdapter[str] = TypeAdapter(EmailStr)


class ContactoInvalidoError(ValueError):
    pass


@dataclass(frozen=True)
class Contacto:
    numero_registro: int
    telefono: str | None
    email: str | None


@dataclass
class Extraccion:
    contactos: list[Contacto] = field(default_factory=list)
    # (número de registro, motivo): datos del origen que no se toman.
    descartados: list[tuple[int, str]] = field(default_factory=list)


def _dato(valor: str) -> str | None:
    limpio = " ".join(valor.split())
    return None if limpio in SIN_DATO else limpio


def extraer(volcado: str) -> Extraccion:
    salida = Extraccion()
    filas = leer_volcado(volcado, ("registro_notarial",))["registro_notarial"]
    vistos: set[int] = set()
    for fila in sorted(filas, key=lambda f: int(f["numero"])):
        numero = int(fila["numero"])
        if numero in vistos:
            raise ContactoInvalidoError(f"El registro {numero} aparece dos veces en el volcado.")
        vistos.add(numero)
        telefono = _dato(fila["telefono"])
        if telefono is not None and len(telefono) > MAX_TELEFONO:
            salida.descartados.append((numero, f"teléfono de más de {MAX_TELEFONO} caracteres"))
            telefono = None
        email = _dato(fila["email"])
        if email is not None:
            try:
                email = _EMAIL.validate_python(email).lower()
            except ValidationError:
                salida.descartados.append((numero, f"correo inválido «{email}»"))
                email = None
        if telefono is not None or email is not None:
            salida.contactos.append(Contacto(numero, telefono, email))
    return salida


def escribir_csv(contactos: list[Contacto], destino: Path) -> None:
    with destino.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(COLUMNAS)
        for c in contactos:
            escritor.writerow([c.numero_registro, c.telefono or "", c.email or ""])


def leer_csv(origen: Path) -> list[Contacto]:
    with origen.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f, delimiter=";")
        if tuple(lector.fieldnames or ()) != COLUMNAS:
            raise ContactoInvalidoError(f"Se esperan las columnas {';'.join(COLUMNAS)}.")
        contactos: list[Contacto] = []
        for linea, fila in enumerate(lector, start=2):
            try:
                numero = int(fila["numero_registro"])
            except ValueError as exc:
                raise ContactoInvalidoError(f"Línea {linea}: número de registro inválido.") from exc
            contactos.append(
                Contacto(numero, _dato(fila["telefono"] or ""), _dato(fila["email"] or ""))
            )
    return contactos


@dataclass
class Carga:
    completados: list[int] = field(default_factory=list)
    sin_cambios: list[int] = field(default_factory=list)
    sin_registro: list[int] = field(default_factory=list)
    # (número, campo, valor en la Suite, valor del origen): no se pisa.
    diferencias: list[tuple[int, str, str, str]] = field(default_factory=list)


async def cargar(
    session: AsyncSession, operador_email: str, contactos: list[Contacto], *, aplicar: bool
) -> Carga:
    # Import diferido: el servicio de la migración arrastra todo el padrón y la carga.
    from app.modules.migracion.service import _operador
    from app.modules.padron import service as padron

    operador = await _operador(session, operador_email)
    registros = {
        r.numero_registro: r for r in (await session.scalars(select(RegistroNotarial))).all()
    }
    resultado = Carga()
    for c in contactos:
        registro = registros.get(c.numero_registro)
        if registro is None:
            resultado.sin_registro.append(c.numero_registro)
            continue
        cambios: dict[str, str] = {}
        for campo, nuevo in (("telefono", c.telefono), ("email", c.email)):
            actual = getattr(registro, campo)
            if nuevo is None or actual == nuevo:
                continue
            if actual:
                resultado.diferencias.append((c.numero_registro, campo, actual, nuevo))
            else:
                cambios[campo] = nuevo
        if not cambios:
            resultado.sin_cambios.append(c.numero_registro)
            continue
        resultado.completados.append(c.numero_registro)
        if aplicar:
            await padron.update_registro(
                session, ORIGEN, operador, registro.id, RegistroUpdate(**cambios)
            )
    return resultado


def _imprimir(r: Carga, *, aplicar: bool) -> None:
    def numeros(lista: list[int]) -> str:
        return ", ".join(str(n) for n in lista) or "—"

    verbo = "completados" if aplicar else "a completar (sin --aplicar no se guarda nada)"
    sys.stdout.write(f"registros {verbo}: {len(r.completados)}\n")
    sys.stdout.write(f"  ya tenían esos datos: {len(r.sin_cambios)}\n")
    sys.stdout.write(f"  no están en la Suite: {numeros(r.sin_registro)}\n")
    for numero, campo, actual, nuevo in r.diferencias:
        sys.stdout.write(
            f"  registro {numero}: {campo} en la Suite «{actual}», en el origen «{nuevo}» "
            "(no se pisa)\n"
        )


async def _cargar_cli(archivo: Path, operador: str, *, aplicar: bool) -> int:
    from app.core.db import get_sessionmaker

    contactos = leer_csv(archivo)
    async with get_sessionmaker()() as session:
        resultado = await cargar(session, operador, contactos, aplicar=aplicar)
    _imprimir(resultado, aplicar=aplicar)
    return 0


def main(argumentos: list[str] | None = None) -> int:
    lector = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = lector.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("extraer", help="Del volcado del sitio a un CSV (en el equipo)")
    p.add_argument("--volcado", type=Path, required=True)
    p.add_argument("--salida", type=Path, required=True)
    p = sub.add_parser("cargar", help="Completa los registros de la Suite (en el servidor)")
    p.add_argument("--archivo", type=Path, required=True)
    p.add_argument("--operador", required=True, help="Correo de un usuario con migracion:ejecutar")
    p.add_argument("--aplicar", action="store_true", help="Guarda los cambios (si no, informa)")
    args = lector.parse_args(argumentos)
    try:
        if args.comando == "extraer":
            if args.salida.exists():
                raise ContactoInvalidoError(f"{args.salida} ya existe: no se sobrescribe.")
            e = extraer(args.volcado.read_text(encoding="utf-8"))
            escribir_csv(e.contactos, args.salida)
            sys.stdout.write(f"registros con contacto: {len(e.contactos)}\n")
            for numero, motivo in e.descartados:
                sys.stdout.write(f"  registro {numero}: {motivo} (no se toma)\n")
            return 0
        # Registra todos los modelos: corriendo solo, SQLAlchemy no resolvería las relaciones.
        import app.db.models  # noqa: F401
        from app.modules.migracion.service import MigracionError

        try:
            return asyncio.run(_cargar_cli(args.archivo, args.operador, aplicar=args.aplicar))
        except MigracionError as exc:
            sys.stderr.write(f"{exc}\n")
            return 1
    except ContactoInvalidoError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
