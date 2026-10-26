"""Cuadratura origen ↔ Suite al centavo (módulo 11 §1.1.3).

Tres fuentes por entidad: el control que declara el sistema anterior, lo leído del lote y lo que
quedó efectivamente en la base (consultado, no tomado de memoria). Cuadra cuando:

- control = leído (el lote está completo), en filas e importes;
- leído = cargado + rechazado (toda fila no cargada tiene su observación bloqueante);
- el saldo de cada registro (boletas no anuladas menos pagos) es el mismo en origen y destino.

Nunca se compensa una diferencia: si algo no cuadra, el informe lo muestra con su magnitud.
"""

import uuid
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.migracion import valores
from app.modules.migracion.carga import Cargado
from app.modules.migracion.catalog import Entidad, EstadoBoletaHistorica, Severidad
from app.modules.migracion.formato import Lote
from app.modules.migracion.models import HistoricoBoleta, HistoricoPago
from app.modules.migracion.validacion import CERO, Staging
from app.modules.padron.models import Adscripcion, Escribano, RegistroNotarial

CON_IMPORTE = (Entidad.BOLETAS, Entidad.PAGOS)


def _texto(valor: Decimal | None) -> str | None:
    return None if valor is None else f"{valor:.2f}"


async def _cargadas(
    session: AsyncSession, c: Cargado, corrida_id: uuid.UUID
) -> dict[Entidad, tuple[int, Decimal | None]]:
    async def contar(modelo: Any, entidad: Entidad) -> int:
        ids = list(c.ids[entidad].values())
        if not ids:
            return 0
        return int(await session.scalar(select(func.count()).where(modelo.id.in_(ids))) or 0)

    async def historico(modelo: Any) -> tuple[int, Decimal]:
        fila = (
            await session.execute(
                select(func.count(), func.coalesce(func.sum(modelo.importe), 0)).where(
                    modelo.corrida_id == corrida_id
                )
            )
        ).one()
        return int(fila[0]), Decimal(fila[1]).quantize(Decimal("0.01"))

    return {
        Entidad.REGISTROS: (await contar(RegistroNotarial, Entidad.REGISTROS), None),
        Entidad.ESCRIBANOS: (await contar(Escribano, Entidad.ESCRIBANOS), None),
        Entidad.CARGOS: (await contar(Adscripcion, Entidad.CARGOS), None),
        Entidad.BOLETAS: await historico(HistoricoBoleta),
        Entidad.PAGOS: await historico(HistoricoPago),
    }


def _saldos_origen(st: Staging) -> dict[int, Decimal]:
    saldo: dict[int, Decimal] = defaultdict(lambda: CERO)
    registro_de = {}
    for b in st.boletas:
        registro_de[b.codigo] = b.numero_registro
        # Toda boleta deja al registro en el informe, aunque esté anulada (saldo 0).
        saldo[b.numero_registro] += b.importe if b.estado != EstadoBoletaHistorica.ANULADA else CERO
    for p in st.pagos:
        saldo[registro_de[p.boleta]] -= p.importe
    return dict(saldo)


async def _saldos_destino(session: AsyncSession, corrida_id: uuid.UUID) -> dict[int, Decimal]:
    emitido = (
        select(
            HistoricoBoleta.registro_id,
            func.sum(HistoricoBoleta.importe).filter(
                HistoricoBoleta.estado != EstadoBoletaHistorica.ANULADA.value
            ),
        )
        .where(HistoricoBoleta.corrida_id == corrida_id)
        .group_by(HistoricoBoleta.registro_id)
    )
    pagado = (
        select(HistoricoBoleta.registro_id, func.sum(HistoricoPago.importe))
        .join(HistoricoBoleta, HistoricoBoleta.id == HistoricoPago.boleta_id)
        .where(HistoricoPago.corrida_id == corrida_id)
        .group_by(HistoricoBoleta.registro_id)
    )
    numeros = dict(
        (await session.execute(select(RegistroNotarial.id, RegistroNotarial.numero_registro))).all()
    )
    saldo: dict[int, Decimal] = defaultdict(lambda: CERO)
    for registro_id, total in (await session.execute(emitido)).all():
        saldo[numeros[registro_id]] += Decimal(total or 0)
    for registro_id, total in (await session.execute(pagado)).all():
        saldo[numeros[registro_id]] -= Decimal(total or 0)
    return {k: v.quantize(Decimal("0.01")) for k, v in saldo.items()}


async def calcular(
    session: AsyncSession, lote: Lote, st: Staging, c: Cargado, corrida_id: uuid.UUID
) -> dict[str, Any]:
    cargadas = await _cargadas(session, c, corrida_id)
    entidades = []
    cuadra = True
    for entidad in Entidad:
        control_filas, control_importe_texto = lote.control[entidad.value]
        control_importe: Decimal | None = None
        control_importe_error = None
        if entidad in CON_IMPORTE:
            try:
                control_importe = valores.importe(control_importe_texto or "")
            except valores.ValorInvalidoError as exc:
                control_importe_error = str(exc)
        leidas = st.leidas[entidad.value]
        rechazadas = st.rechazadas[entidad.value]
        cargadas_filas, importe_cargado = cargadas[entidad]
        fila: dict[str, Any] = {
            "entidad": entidad.value,
            "control_filas": control_filas,
            "leidas": leidas,
            "rechazadas": rechazadas,
            "cargadas": cargadas_filas,
            "cuadra_filas": control_filas == leidas == rechazadas + cargadas_filas,
        }
        if entidad in CON_IMPORTE:
            leido = st.importe_leido[entidad.value]
            rechazado = st.importe_rechazado[entidad.value]
            ilegibles = st.importe_ilegible[entidad.value]
            fila |= {
                "control_importe": _texto(control_importe),
                "control_importe_error": control_importe_error,
                "importe_leido": _texto(leido),
                "importe_rechazado": _texto(rechazado),
                "importe_cargado": _texto(importe_cargado),
                "filas_importe_ilegible": ilegibles,
                "cuadra_importe": (
                    control_importe is not None
                    and ilegibles == 0
                    and control_importe == leido
                    and importe_cargado is not None
                    and leido == rechazado + importe_cargado
                ),
            }
            cuadra = cuadra and fila["cuadra_importe"]
        cuadra = cuadra and fila["cuadra_filas"]
        entidades.append(fila)

    origen, destino = _saldos_origen(st), await _saldos_destino(session, corrida_id)
    diferencias = [
        {
            "registro": numero,
            "origen": _texto(origen.get(numero)),
            "destino": _texto(destino.get(numero)),
        }
        for numero in sorted(set(origen) | set(destino))
        if origen.get(numero, CERO) != destino.get(numero, CERO)
    ]
    cuadra = cuadra and not diferencias

    por_estado: dict[str, list[Any]] = defaultdict(lambda: [0, CERO])
    for b in st.boletas:
        por_estado[b.estado][0] += 1
        por_estado[b.estado][1] += b.importe
    severidades = Counter(o.severidad for o in st.observaciones)
    return {
        "cuadra": cuadra,
        "entidades": entidades,
        "saldos": {
            "registros": len(set(origen) | set(destino)),
            "deuda_total_origen": _texto(sum(origen.values(), CERO)),
            "deuda_total_destino": _texto(sum(destino.values(), CERO)),
            "diferencias": diferencias,
        },
        "boletas_por_estado": [
            {"estado": e, "filas": n, "importe": _texto(i)}
            for e, (n, i) in sorted(por_estado.items())
        ],
        "circunscripciones_nuevas": c.circunscripciones_nuevas,
        "bloqueantes": severidades[Severidad.BLOQUEANTE],
        "advertencias": severidades[Severidad.ADVERTENCIA],
        "observaciones_por_codigo": dict(
            sorted(Counter(o.codigo for o in st.observaciones).items())
        ),
        "codificaciones": lote.codificaciones,
    }
