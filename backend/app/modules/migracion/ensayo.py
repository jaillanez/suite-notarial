"""Ensayo cronometrado del corte y de la reversa (DoD de la Fase 10).

Sobre una base descartable (`suite_notarial_ensayo`), con datos sintéticos:

1. esquema desde cero (migraciones);
2. operador, Tesorería y Caja de ensayo;
3. tres simulacros del mismo lote y conformidad de ambas áreas sobre el último;
4. respaldo, carga definitiva y verificación de la cuadratura;
5. reversa al respaldo y verificación de que la base volvió exactamente al estado previo
   (conteos, sin carga definitiva, la aplicación vuelve a escribir).

Cada paso se cronometra; el ensayo falla si la reversa (respaldo + restauración + verificación)
supera el objetivo de 30 minutos. Deja un informe en JSON y en Markdown.
"""

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.common.audit import AuditEvent, record_audit
from app.modules.iam import passwords
from app.modules.iam.models import Role, User, UserRole
from app.modules.migracion import reversa, service, sintetico
from app.modules.migracion.catalog import AreaConformidad, EstadoCorrida, ModoCorrida
from app.modules.migracion.homologacion import EJEMPLO
from app.modules.migracion.models import Conformidad, Corrida, HistoricoBoleta, HistoricoPago
from app.modules.padron.models import Adscripcion, Escribano, Persona, RegistroNotarial

BACKEND = Path(__file__).resolve().parents[3]
OBJETIVO_REVERSA_S = 30 * 60
TABLAS_CONTADAS = (
    Persona,
    Escribano,
    RegistroNotarial,
    Adscripcion,
    HistoricoBoleta,
    HistoricoPago,
)


class EnsayoFallidoError(RuntimeError):
    pass


@dataclass
class Informe:
    base: str
    inicio: str
    pasos: list[dict[str, Any]] = field(default_factory=list)
    conteos_previos: dict[str, int] = field(default_factory=dict)
    conteos_cargados: dict[str, int] = field(default_factory=dict)
    conteos_restaurados: dict[str, int] = field(default_factory=dict)
    reversa_s: float = 0.0
    objetivo_s: int = OBJETIVO_REVERSA_S
    resultado: str = "EN_CURSO"

    def paso(self, nombre: str, ms: int, **detalle: Any) -> None:
        self.pasos.append({"paso": nombre, "ms": ms, **detalle})


async def _medir[T](funcion: Callable[[], Awaitable[T]]) -> tuple[T, int]:
    inicio = time.perf_counter_ns()
    resultado = await funcion()
    return resultado, (time.perf_counter_ns() - inicio) // 1_000_000


def _alembic(owner_url: str, app_url: str, *args: str) -> None:
    entorno = {"MIGRATIONS_DATABASE_URL": owner_url, "DATABASE_URL": app_url}
    resultado = subprocess.run(  # noqa: S603 - comando fijo del propio proyecto
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, **entorno},
        capture_output=True,
        text=True,
        check=False,
    )
    if resultado.returncode != 0:
        raise EnsayoFallidoError(f"alembic {' '.join(args)}: {resultado.stderr.strip()[-2000:]}")


async def _conteos(maker: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with maker() as session:
        return {
            t.__tablename__: int(await session.scalar(select(func.count()).select_from(t)) or 0)
            for t in TABLAS_CONTADAS
        }


async def _usuario(session: AsyncSession, email: str, rol: str, n: int) -> User:
    role = (await session.execute(select(Role).where(Role.code == rol))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email,
        cuit=sintetico.cuit_sintetico(sintetico.DNI_BASE - n),
        full_name=f"Ensayo {rol}",
        hashed_password=passwords.hash_password(secrets.token_urlsafe(24)),
        is_verified=True,
    )
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id))
    return user


async def ensayar(
    owner_url: str, app_url: str, salida: Path, *, registros: int = 30, periodos: int = 12
) -> Informe:
    informe = Informe(base=owner_url.rsplit("/", 1)[-1], inicio=datetime.now(UTC).isoformat())

    inicio = time.perf_counter_ns()
    _alembic(owner_url, app_url, "downgrade", "base")
    _alembic(owner_url, app_url, "upgrade", "head")
    informe.paso("esquema desde cero", (time.perf_counter_ns() - inicio) // 1_000_000)

    engine = create_async_engine(app_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            operador = await _usuario(session, "operador@ensayo.test", "ROLE_ADMIN", 1)
            tesoreria = await _usuario(session, "tesoreria@ensayo.test", "ROLE_TESORERIA", 2)
            caja = await _usuario(session, "caja@ensayo.test", "ROLE_CAJA", 3)
            await session.commit()

        trabajo = Path(tempfile.mkdtemp(prefix="ensayo-corte-"))
        lote = trabajo / "lote"
        resumen = sintetico.generar(lote, registros=registros, periodos=periodos)
        # Homologación de ENSAYO: la de ejemplo con la marca quitada, solo en esta base.
        datos = json.loads(EJEMPLO.read_text(encoding="utf-8"))
        datos["es_ejemplo"] = False
        homologacion = trabajo / "homologacion_ensayo.json"
        homologacion.write_text(json.dumps(datos), encoding="utf-8")
        informe.paso("lote sintético", 0, **resumen.__dict__)

        ultimo = None
        for n in range(1, 4):
            resultado, ms = await _medir(
                lambda: service.correr(
                    lote,
                    ModoCorrida.SIMULACRO,
                    operador.email,
                    homologacion_ruta=homologacion,
                    maker=maker,
                )
            )
            if not resultado.cuadra:
                raise EnsayoFallidoError(f"El simulacro {n} no cuadró.")
            informe.paso(f"simulacro {n}", ms, cuadra=True)
            ultimo = resultado.corrida_id
        assert ultimo is not None  # noqa: S101

        async with maker() as session:
            for area, firmante in (
                (AreaConformidad.TESORERIA, tesoreria),
                (AreaConformidad.CAJA, caja),
            ):
                session.add(
                    Conformidad(
                        id=uuid.uuid4(),
                        corrida_id=ultimo,
                        area=area.value,
                        user_id=firmante.id,
                        observaciones="Conformidad de ensayo",
                        firmada_en=datetime.now(UTC),
                    )
                )
                record_audit(
                    session,
                    service.CONSOLA,
                    AuditEvent.MIGRACION_CONFORMIDAD,
                    actor_user_id=firmante.id,
                    details={"corrida_id": str(ultimo), "area": area.value, "ensayo": True},
                )
            await session.commit()
        informe.paso("conformidades de Tesorería y Caja", 0)

        informe.conteos_previos = await _conteos(maker)
        respaldo = salida / "respaldo-previo-a-la-carga.dump"
        inicio = time.perf_counter_ns()
        tamano = reversa.respaldar(owner_url, respaldo)
        respaldo_ms = (time.perf_counter_ns() - inicio) // 1_000_000
        informe.paso("respaldo", respaldo_ms, bytes=tamano)

        definitiva, ms = await _medir(
            lambda: service.correr(
                lote,
                ModoCorrida.DEFINITIVA,
                operador.email,
                homologacion_ruta=homologacion,
                maker=maker,
            )
        )
        if not (definitiva.cuadra and definitiva.estado is EstadoCorrida.CARGADA):
            raise EnsayoFallidoError("La carga definitiva no cuadró.")
        informe.conteos_cargados = await _conteos(maker)
        informe.paso("carga definitiva", ms, cuadra=True)

        # Se libera toda conexión antes de restaurar (la restauración borra y recrea tablas).
        await engine.dispose()
        inicio = time.perf_counter_ns()
        reversa.restaurar(owner_url, respaldo)
        restauracion_ms = (time.perf_counter_ns() - inicio) // 1_000_000
        informe.paso("reversa al respaldo", restauracion_ms)

        inicio = time.perf_counter_ns()
        informe.conteos_restaurados = await _conteos(maker)
        if informe.conteos_restaurados != informe.conteos_previos:
            raise EnsayoFallidoError("Tras la reversa, los conteos no coinciden con los previos.")
        async with maker() as session:
            quedan = await session.scalar(
                select(func.count()).where(Corrida.modo == ModoCorrida.DEFINITIVA.value)
            )
            if quedan:
                raise EnsayoFallidoError("Tras la reversa sigue registrada la carga definitiva.")
            # La aplicación vuelve a operar: escribe (y se revierte) con su rol.
            await session.execute(text("SELECT 1 FROM security_users LIMIT 1"))
            await session.execute(
                text("INSERT INTO padron_circunscripciones (nombre) VALUES ('Verificación')")
            )
            await session.rollback()
        verificacion_ms = (time.perf_counter_ns() - inicio) // 1_000_000
        informe.paso("verificación posterior", verificacion_ms)

        informe.reversa_s = (respaldo_ms + restauracion_ms + verificacion_ms) / 1000
        if informe.reversa_s > OBJETIVO_REVERSA_S:
            raise EnsayoFallidoError(
                f"La reversa tardó {informe.reversa_s:.0f} s: supera el objetivo de 30 minutos."
            )
        informe.resultado = "OK"
    except Exception:
        informe.resultado = "FALLIDO"
        raise
    finally:
        await engine.dispose()
        _escribir_informe(informe, salida)
    return informe


def _escribir_informe(informe: Informe, salida: Path) -> None:
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "informe-ensayo.json").write_text(
        json.dumps(informe.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lineas = [
        "# Ensayo de corte y reversa",
        "",
        f"- Base: `{informe.base}` · inicio {informe.inicio}",
        f"- Resultado: **{informe.resultado}**",
        f"- Reversa (respaldo + restauración + verificación): {informe.reversa_s:.1f} s "
        f"(objetivo: menos de {informe.objetivo_s // 60} minutos)",
        "",
        "| Paso | Tiempo |",
        "|------|-------:|",
        *[f"| {p['paso']} | {p['ms'] / 1000:.2f} s |" for p in informe.pasos],
        "",
        "| Tabla | Antes | Con la carga | Tras la reversa |",
        "|-------|------:|-------------:|----------------:|",
        *[
            f"| {t} | {informe.conteos_previos.get(t, '—')} | "
            f"{informe.conteos_cargados.get(t, '—')} | {informe.conteos_restaurados.get(t, '—')} |"
            for t in (m.__tablename__ for m in TABLAS_CONTADAS)
        ],
        "",
    ]
    (salida / "informe-ensayo.md").write_text("\n".join(lineas), encoding="utf-8")
