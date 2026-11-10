"""padron: departamento del registro y fecha desde del cargo «a completar»

El sistema anterior de la Caja no tiene el departamento de los registros ni la fecha de
designación de algunos cargos: se migran vacíos y la Caja los completa después.

Revision ID: c3d8e1f2a4b6
Revises: ab95fae36072
Create Date: 2026-11-10 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d8e1f2a4b6"
down_revision: str | None = "ab95fae36072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "padron_registros_notariales",
        "departamento",
        existing_type=sa.String(length=100),
        nullable=True,
    )
    op.alter_column("padron_adscripciones", "fecha_desde", existing_type=sa.Date(), nullable=True)


def downgrade() -> None:
    # No se inventan datos: si quedan vacíos, la base no vuelve atrás hasta completarlos.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM padron_registros_notariales WHERE departamento IS NULL)
               OR EXISTS (SELECT 1 FROM padron_adscripciones WHERE fecha_desde IS NULL) THEN
                RAISE EXCEPTION 'Hay registros sin departamento o cargos sin fecha desde: '
                    'completalos antes de volver atrás esta migración.';
            END IF;
        END $$;
        """
    )
    op.alter_column("padron_adscripciones", "fecha_desde", existing_type=sa.Date(), nullable=False)
    op.alter_column(
        "padron_registros_notariales",
        "departamento",
        existing_type=sa.String(length=100),
        nullable=False,
    )
