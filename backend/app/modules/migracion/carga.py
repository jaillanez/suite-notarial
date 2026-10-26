"""Carga del staging validado en la Suite, dentro de la transacción del llamador.

Inserta en orden de dependencias (circunscripciones, registros, personas y escribanos, cargos,
boletas y pagos históricos) con ids generados acá, y deja el mapeo código del origen → id.
No borra ni actualiza nada existente: lo que choca con datos de la Suite ya quedó observado.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.migracion.catalog import Entidad
from app.modules.migracion.models import HistoricoBoleta, HistoricoPago, Mapeo
from app.modules.migracion.validacion import Staging
from app.modules.padron.models import (
    Adscripcion,
    Circunscripcion,
    Escribano,
    Persona,
    RegistroNotarial,
)

LOTE_INSERT = 1000


@dataclass
class Cargado:
    """Ids creados por entidad (código del origen → id en la Suite)."""

    ids: dict[Entidad, dict[str, uuid.UUID]] = field(default_factory=lambda: defaultdict(dict))
    registro_por_numero: dict[int, uuid.UUID] = field(default_factory=dict)
    circunscripciones_nuevas: int = 0


async def _insertar(session: AsyncSession, tabla: object, filas: list[dict[str, object]]) -> None:
    for i in range(0, len(filas), LOTE_INSERT):
        await session.execute(insert(tabla), filas[i : i + LOTE_INSERT])  # type: ignore[arg-type]


async def cargar(
    session: AsyncSession, st: Staging, corrida_id: uuid.UUID, operador_id: uuid.UUID
) -> Cargado:
    # Habilita los INSERT en el histórico solo para esta transacción (ver trigger).
    await session.execute(text("SET LOCAL suite.migracion = 'on'"))
    c = Cargado()

    existentes = {
        nombre.lower(): cid
        for nombre, cid in (
            await session.execute(select(Circunscripcion.nombre, Circunscripcion.id))
        ).all()
    }
    nuevas: list[dict[str, object]] = []
    for nombre in sorted({r.circunscripcion for r in st.registros}):
        if nombre.lower() not in existentes:
            existentes[nombre.lower()] = uuid.uuid4()
            nuevas.append(
                {
                    "id": existentes[nombre.lower()],
                    "nombre": nombre,
                    "created_by_user_id": operador_id,
                }
            )
    await _insertar(session, Circunscripcion, nuevas)
    c.circunscripciones_nuevas = len(nuevas)

    registros = []
    for r in st.registros:
        rid = uuid.uuid4()
        c.ids[Entidad.REGISTROS][r.codigo] = rid
        c.registro_por_numero[r.numero] = rid
        registros.append(
            {
                "id": rid,
                "numero_registro": r.numero,
                "nombre_fantasia": r.nombre_fantasia,
                "circunscripcion_id": existentes[r.circunscripcion.lower()],
                "departamento": r.departamento,
                "domicilio_legal": r.domicilio,
                "fecha_creacion": r.fecha_creacion,
                "estado": r.estado,
                "created_by_user_id": operador_id,
            }
        )
    await _insertar(session, RegistroNotarial, registros)

    personas, escribanos = [], []
    escribano_por_matricula: dict[int, uuid.UUID] = {}
    for e in st.escribanos:
        pid, eid = uuid.uuid4(), uuid.uuid4()
        c.ids[Entidad.ESCRIBANOS][e.codigo] = eid
        escribano_por_matricula[e.matricula] = eid
        personas.append(
            {
                "id": pid,
                "cuit": e.cuit,
                "tipo_documento": e.tipo_documento,
                "numero_documento": e.numero_documento,
                "apellido": e.apellido,
                "nombre": e.nombre,
                "fecha_nacimiento": e.fecha_nacimiento,
                "email": e.email,
                "created_by_user_id": operador_id,
            }
        )
        escribanos.append(
            {
                "id": eid,
                "persona_id": pid,
                "matricula_numero": e.matricula,
                "fecha_matriculacion": e.fecha_matriculacion,
                "estado_matricula": e.estado,
                "created_by_user_id": operador_id,
            }
        )
    await _insertar(session, Persona, personas)
    await _insertar(session, Escribano, escribanos)

    cargos = []
    for cargo in st.cargos:
        aid = uuid.uuid4()
        c.ids[Entidad.CARGOS][cargo.codigo] = aid
        cargos.append(
            {
                "id": aid,
                "escribano_id": escribano_por_matricula[cargo.matricula],
                "registro_id": c.registro_por_numero[cargo.numero_registro],
                "cargo": cargo.cargo,
                "fecha_desde": cargo.desde,
                "fecha_hasta": cargo.hasta,
                "is_current": cargo.hasta is None,
                "motivo_cierre": "Migrado del sistema anterior" if cargo.hasta else None,
                "created_by_user_id": operador_id,
            }
        )
    await _insertar(session, Adscripcion, cargos)

    boletas = []
    for b in st.boletas:
        bid = uuid.uuid4()
        c.ids[Entidad.BOLETAS][b.codigo] = bid
        boletas.append(
            {
                "id": bid,
                "corrida_id": corrida_id,
                "codigo_legado": b.codigo,
                "registro_id": c.registro_por_numero[b.numero_registro],
                "periodo": b.periodo,
                "numero_boleta": b.numero_boleta,
                "fecha_emision": b.emision,
                "fecha_vencimiento": b.vencimiento,
                "importe": b.importe,
                "estado": b.estado,
            }
        )
    await _insertar(session, HistoricoBoleta, boletas)

    pagos = []
    for p in st.pagos:
        pago_id = uuid.uuid4()
        c.ids[Entidad.PAGOS][p.codigo] = pago_id
        pagos.append(
            {
                "id": pago_id,
                "corrida_id": corrida_id,
                "codigo_legado": p.codigo,
                "boleta_id": c.ids[Entidad.BOLETAS][p.boleta],
                "fecha_pago": p.fecha,
                "importe": p.importe,
                "medio": p.medio,
            }
        )
    await _insertar(session, HistoricoPago, pagos)

    await _insertar(
        session,
        Mapeo,
        [
            {
                "id": uuid.uuid4(),
                "corrida_id": corrida_id,
                "entidad": entidad.value,
                "codigo_legado": codigo,
                "destino_id": destino,
            }
            for entidad, codigos in c.ids.items()
            for codigo, destino in codigos.items()
        ],
    )
    return c
