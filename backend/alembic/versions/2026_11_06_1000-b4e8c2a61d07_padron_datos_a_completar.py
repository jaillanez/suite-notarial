"""padron_datos_a_completar: matrícula, fecha de matriculación, CUIT y documento opcionales

El listado del sistema anterior trae escribanos sin matrícula, sin fecha de alta y personas
históricas sin CUIT ni documento. Se migran igual y quedan «a completar»: la Caja los completa
después desde la ficha del escribano. El alta manual los sigue exigiendo.

La unicidad se mantiene para los valores cargados (un UNIQUE admite varios NULL en PostgreSQL)
y los CHECK existentes (`matricula_numero > 0`, CUIT de 11 dígitos) pasan con NULL.

Revision ID: b4e8c2a61d07
Revises: 7a3d9e1c5b22
Create Date: 2026-11-06 10:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4e8c2a61d07"
down_revision: Union[str, Sequence[str], None] = "7a3d9e1c5b22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (tabla, columna, tipo)
COLUMNAS = (
    ("padron_escribanos", "matricula_numero", sa.Integer()),
    ("padron_escribanos", "fecha_matriculacion", sa.Date()),
    ("padron_personas", "cuit", sa.String(length=11)),
    ("padron_personas", "numero_documento", sa.String(length=15)),
)


def upgrade() -> None:
    for tabla, columna, tipo in COLUMNAS:
        op.alter_column(tabla, columna, existing_type=tipo, nullable=True)


def downgrade() -> None:
    # Volver a NOT NULL exige que no quede ningún dato a completar: no se inventan valores.
    bind = op.get_bind()
    pendientes = []
    for tabla, columna, _ in COLUMNAS:
        cantidad = bind.execute(
            sa.text(f"SELECT count(*) FROM {tabla} WHERE {columna} IS NULL")  # noqa: S608
        ).scalar_one()
        if cantidad:
            pendientes.append(f"{tabla}.{columna}: {cantidad}")
    if pendientes:
        raise RuntimeError(
            "No se puede volver atrás: hay datos a completar sin cargar ("
            + "; ".join(pendientes)
            + "). Completalos desde la ficha del escribano antes del downgrade."
        )
    for tabla, columna, tipo in COLUMNAS:
        op.alter_column(tabla, columna, existing_type=tipo, nullable=False)
