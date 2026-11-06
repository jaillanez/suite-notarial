"""Planillas SINTÉTICAS de aportes y puntos (misma estructura que la hoja «Actualizada» de la
Caja, con nombres y cifras inventados) y escribanos de prueba con nombre propio."""

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date
from itertools import count
from pathlib import Path
from typing import Any

import pyotp
import pytest
import xlwt
from fastapi import FastAPI
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.models import User
from app.modules.padron.models import Escribano, Persona
from app.modules.previsional.planilla import Celda, numero
from tests.ddjj.conftest import _client
from tests.iam.factories import make_user, synthetic_cuit
from tests.iam.test_rbac import login

_matriculas = count(60_000)

# Celda de un ejercicio: (aportes, puntos) o None si está vacía.
Par = tuple[Any, Any] | None


@dataclass
class Hoja:
    """Contenido de la hoja «Actualizada»: años, afiliados y filas de resumen."""

    anios: list[int] = field(default_factory=lambda: [1990, 1991])
    afiliados: list[tuple[str | None, list[Par]]] = field(default_factory=list)
    totales: list[Any] | None = None
    cantidades: list[Any] | None = None
    medios: list[Any] | None = None

    def filas(self) -> list[list[Any]]:
        n = len(self.anios)
        cab: list[Any] = ["PERIODO"]
        ini: list[Any] = ["Fecha de Inicio del periodo"]
        fin: list[Any] = ["Fecha de cierre del periodo"]
        sub: list[Any] = ["AFILIADO"]
        for a in self.anios:
            cab += [a, None]
            ini += [date(a - 1, 9, 1), None]
            fin += [date(a, 8, 31), None]
            sub += ["APORTES", "  PUNTOS"]
        cab += ["TOTAL", "TOTAL "]
        filas: list[list[Any]] = [cab, ini, fin, [], sub]
        for nombre, pares in self.afiliados:
            fila: list[Any] = [nombre]
            for par in pares:
                fila += list(par) if par else [None, None]
            filas.append(fila)
        filas.append([])
        totales = self.totales or [sum_aportes(self, i) for i in range(n)]
        cantidades = self.cantidades or [2] * n
        medios = self.medios or [13.808774468085103] * n
        filas.append(["TOTAL DE APORTES INGRESADOS", *_intercalar(totales)])
        filas.append([])
        filas.append(
            ["CANTIDAD DE AFILIADOS (estimada en años anteriores)", *_intercalar(cantidades)]
        )
        filas.append(["CANTIDAD DE AFILIADOS X 100", *_intercalar([c * 100 for c in cantidades])])
        filas.append(["APORTE MEDIO DEL EJERCICIO", *_intercalar(medios)])
        return filas


def celdas(filas: list[list[Any]]) -> list[list[Celda]]:
    """Como las entrega el lector: números como Decimal, fechas como date."""
    return [
        [v if v is None or isinstance(v, str | date) else numero(v) for v in fila] for fila in filas
    ]


def _intercalar(valores: list[Any]) -> list[Any]:
    out: list[Any] = []
    for v in valores:
        out += [v, None]
    return out


def sum_aportes(hoja: Hoja, i: int) -> Any:
    total: Any = 0
    for _, pares in hoja.afiliados:
        par = pares[i] if i < len(pares) else None
        if par and par[0] is not None:
            total += par[0]
    return total


def escribir_xlsx(hoja: Hoja, ruta: Path, *, nombre_hoja: str = "Actualizada") -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = nombre_hoja
    for r, fila in enumerate(hoja.filas(), start=1):
        for c, valor in enumerate(fila, start=1):
            if valor is not None:
                ws.cell(row=r, column=c, value=valor)
    wb.save(ruta)
    return ruta


def escribir_xls(hoja: Hoja, ruta: Path) -> Path:
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Actualizada")
    fecha = xlwt.easyxf(num_format_str="DD/MM/YYYY")
    for r, fila in enumerate(hoja.filas()):
        for c, valor in enumerate(fila):
            if valor is None:
                continue
            if isinstance(valor, date):
                ws.write(r, c, valor, fecha)
            else:
                ws.write(r, c, valor)
    wb.add_sheet("Informe para Escribano")
    wb.save(str(ruta))
    return ruta


def hoja_basica() -> Hoja:
    """Tres afiliados ficticios en dos ejercicios; los puntos de 1990 suman 100 por afiliado."""
    return Hoja(
        anios=[1990, 1991],
        afiliados=[
            ("PRUEBA  Ana Sintética", [(82466.667256, 97.639503), (100.5, 50.0)]),
            ("EJEMPLO GÓMEZ Luis", [(1000, 102.360497), None]),
            ("FICTICIO Pedro S.", [None, (0, 150.0)]),
            (None, [(5, 5), (5, 5)]),  # cifras sin nombre: no se cargan
            ("VACÍO Total", [(0, 0), None]),  # sin datos: no genera filas
        ],
        totales=[83466.667256, 100.5],
        cantidades=[2, 2],
        medios=[417.333336, 0.502500],
    )


@pytest.fixture
def planilla_xlsx(tmp_path: Path) -> Callable[..., Path]:
    def crear(hoja: Hoja | None = None, nombre: str = "planilla.xlsx") -> Path:
        return escribir_xlsx(hoja or hoja_basica(), tmp_path / nombre)

    return crear


async def crear_escribano(
    session: AsyncSession, apellido: str, nombre: str, user: User | None = None
) -> Escribano:
    persona = Persona(
        id=uuid.uuid4(),
        cuit=synthetic_cuit(),
        numero_documento="30999888",
        apellido=apellido,
        nombre=nombre,
    )
    session.add(persona)
    escribano = Escribano(
        id=uuid.uuid4(),
        persona_id=persona.id,
        user_id=user.id if user else None,
        matricula_numero=next(_matriculas),
        fecha_matriculacion=date(1985, 1, 1),
        estado_matricula="ACTIVO",
    )
    session.add(escribano)
    await session.flush()
    return escribano


@pytest.fixture
async def operador(db_session: AsyncSession) -> User:
    """Usuario de Caja con puntos:manage (la carga por consola no pide 2FA)."""
    return await make_user(db_session, roles=("ROLE_CAJA",))


async def _staff(app: FastAPI, session: AsyncSession, rol: str) -> AsyncIterator[AsyncClient]:
    secret = pyotp.random_base32()
    user = await make_user(session, roles=(rol,), totp_secret=secret)
    async with await _client(app) as ac:
        await login(ac, user, secret)
        yield ac


@pytest.fixture
async def caja(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async for ac in _staff(app, db_session, "ROLE_CAJA"):
        yield ac


@pytest.fixture
async def tesoreria_ac(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async for ac in _staff(app, db_session, "ROLE_TESORERIA"):
        yield ac


@dataclass
class Notario:
    user: User
    escribano: Escribano
    client: AsyncClient


@pytest.fixture
async def notario_ana(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[Notario]:
    """Escribana con cuenta de autogestión, cuyo nombre coincide con la planilla básica."""
    user = await make_user(db_session)
    escribano = await crear_escribano(db_session, "Prueba", "Ana Sintética", user)
    await db_session.commit()
    async with await _client(app) as ac:
        await login(ac, user)
        yield Notario(user, escribano, ac)
