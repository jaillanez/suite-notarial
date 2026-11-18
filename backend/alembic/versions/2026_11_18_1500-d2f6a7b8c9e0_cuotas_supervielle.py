"""cuotas_supervielle: las cuotas de préstamo en pesos también se pagan con el botón Supervielle

Decisión de la Caja (Horacio Quiroga, 17/11/2026): las cuotas de los préstamos se pagan por el
botón Supervielle y la comisión la absorbe la Caja.

- `pagos_supervielle` pasa a registrar deudas de una boleta o de una cuota (`cuota_id`), nunca de
  las dos. Las deudas existentes son todas de boletas.
- `confirmado_por_user_id` y `confirmado_en`: Tesorería confirmó el cobro de la cuota y recién
  ahí la cuota pasó a pagada (regla PAGO). Una cuota se confirma una sola vez.

Revision ID: d2f6a7b8c9e0
Revises: c1e5f6a7b8d9
Create Date: 2026-11-18 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2f6a7b8c9e0"
down_revision: Union[str, None] = "c1e5f6a7b8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "pagos_supervielle"
CHECKS = {
    "boleta_o_cuota": "(boleta_id IS NULL) <> (cuota_id IS NULL)",
    "confirmacion_completa": "(confirmado_en IS NULL) = (confirmado_por_user_id IS NULL)",
    "confirma_solo_cuota": "confirmado_en IS NULL OR cuota_id IS NOT NULL",
}


def upgrade() -> None:
    op.add_column(TABLA, sa.Column("cuota_id", sa.UUID(), nullable=True))
    op.add_column(TABLA, sa.Column("confirmado_por_user_id", sa.UUID(), nullable=True))
    op.add_column(TABLA, sa.Column("confirmado_en", sa.DateTime(timezone=True), nullable=True))
    op.alter_column(TABLA, "boleta_id", existing_type=sa.UUID(), nullable=True)
    op.create_foreign_key(
        op.f("fk_pagos_supervielle_cuota_id_prestamos_cuotas"),
        TABLA,
        "prestamos_cuotas",
        ["cuota_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_pagos_supervielle_confirmado_por_user_id_security_users"),
        TABLA,
        "security_users",
        ["confirmado_por_user_id"],
        ["id"],
    )
    op.create_index(op.f("ix_pagos_supervielle_cuota_id"), TABLA, ["cuota_id"], unique=False)
    op.create_index(
        "uq_pagos_supervielle_cuota_confirmada",
        TABLA,
        ["cuota_id"],
        unique=True,
        postgresql_where=sa.text("confirmado_en IS NOT NULL"),
    )
    for nombre, condicion in CHECKS.items():
        op.create_check_constraint(op.f(f"ck_pagos_supervielle_{nombre}"), TABLA, condicion)


def downgrade() -> None:
    # Volver atrás borraría a qué cuota corresponde cada deuda: solo sin deudas de cuotas.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pagos_supervielle WHERE cuota_id IS NOT NULL) THEN
                RAISE EXCEPTION 'Hay cuotas publicadas en el botón Supervielle: no se puede volver atrás';
            END IF;
        END;
        $$;
        """
    )
    for nombre in reversed(CHECKS):
        op.drop_constraint(op.f(f"ck_pagos_supervielle_{nombre}"), TABLA, type_="check")
    op.drop_index(
        "uq_pagos_supervielle_cuota_confirmada",
        table_name=TABLA,
        postgresql_where=sa.text("confirmado_en IS NOT NULL"),
    )
    op.drop_index(op.f("ix_pagos_supervielle_cuota_id"), table_name=TABLA)
    op.drop_constraint(
        op.f("fk_pagos_supervielle_confirmado_por_user_id_security_users"),
        TABLA,
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_pagos_supervielle_cuota_id_prestamos_cuotas"), TABLA, type_="foreignkey"
    )
    op.alter_column(TABLA, "boleta_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column(TABLA, "confirmado_en")
    op.drop_column(TABLA, "confirmado_por_user_id")
    op.drop_column(TABLA, "cuota_id")
