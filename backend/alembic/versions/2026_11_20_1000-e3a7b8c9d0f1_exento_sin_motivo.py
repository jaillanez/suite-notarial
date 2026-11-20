"""exento_sin_motivo: un acto exento ya no está obligado a declarar el motivo

Pedido de la Caja (Horacio Quiroga, 20/11/2026): el motivo de la exención es técnico y no se
le pregunta al escribano al cargar. Se puede seguir guardando (los exentos del vademécum lo
traen), pero solo en un acto exento.

Revision ID: e3a7b8c9d0f1
Revises: d2f6a7b8c9e0
Create Date: 2026-11-20 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "e3a7b8c9d0f1"
down_revision: Union[str, None] = "d2f6a7b8c9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "ddjj_actos"
NOMBRE = op.f("ck_ddjj_actos_exento_con_motivo")


def upgrade() -> None:
    op.drop_constraint(NOMBRE, TABLA, type_="check")
    op.create_check_constraint(NOMBRE, TABLA, "motivo_exencion IS NULL OR categoria = 'EXENTO'")


def downgrade() -> None:
    # Volver atrás exige el motivo en todos los exentos: solo si ninguno quedó sin motivo.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM ddjj_actos WHERE categoria = 'EXENTO' AND motivo_exencion IS NULL
            ) THEN
                RAISE EXCEPTION 'Hay actos exentos sin motivo: no se puede volver atrás';
            END IF;
        END;
        $$;
        """
    )
    op.drop_constraint(NOMBRE, TABLA, type_="check")
    op.create_check_constraint(
        NOMBRE, TABLA, "(categoria = 'EXENTO') = (motivo_exencion IS NOT NULL)"
    )
