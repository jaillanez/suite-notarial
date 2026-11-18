"""iva_comision_supervielle: vigencia del IVA con que se estimó la comisión

La comisión estimada de cada pago Supervielle suma el IVA (el banco confirmó el 18/11/2026 que
sus porcentajes no lo incluyen). `vigencia_comision_iva_id` guarda la vigencia del parámetro
`IVA_COMISION_SPV` usada (regla SNAP), como ya se hace con la del botón y la del medio.

Revision ID: c1e5f6a7b8d9
Revises: b9d4e5f6a7c8
Create Date: 2026-11-18 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1e5f6a7b8d9"
down_revision: Union[str, None] = "b9d4e5f6a7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pagos_supervielle",
        sa.Column("vigencia_comision_iva_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_pagos_supervielle_vigencia_comision_iva_id_parametros_vigencias"),
        "pagos_supervielle",
        "parametros_vigencias",
        ["vigencia_comision_iva_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_pagos_supervielle_vigencia_comision_iva_id_parametros_vigencias"),
        "pagos_supervielle",
        type_="foreignkey",
    )
    op.drop_column("pagos_supervielle", "vigencia_comision_iva_id")
