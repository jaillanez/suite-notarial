"""vigencia_retirada: una propuesta pendiente se puede retirar (para descartarla o corregirla)

Revision ID: 7a3d9e1c5b22
Revises: 5c1e7d2a9b40
Create Date: 2026-10-28 11:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = "7a3d9e1c5b22"
down_revision: Union[str, Sequence[str], None] = "5c1e7d2a9b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "parametros_vigencias"
CHECK = "ck_parametros_vigencias_estado_valido"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), TABLA, type_="check")
    op.create_check_constraint(
        op.f(CHECK), TABLA, "estado IN ('PENDIENTE_APROBACION', 'VIGENTE', 'RECHAZADA', 'RETIRADA')"
    )


def downgrade() -> None:
    # Una retirada nunca entró en vigencia: al volver atrás se registra como rechazada.
    op.execute(f"ALTER TABLE {TABLA} DISABLE TRIGGER parametros_vigencias_guard")
    op.execute(f"UPDATE {TABLA} SET estado = 'RECHAZADA' WHERE estado = 'RETIRADA'")
    op.execute(f"ALTER TABLE {TABLA} ENABLE TRIGGER parametros_vigencias_guard")
    op.drop_constraint(op.f(CHECK), TABLA, type_="check")
    op.create_check_constraint(
        op.f(CHECK), TABLA, "estado IN ('PENDIENTE_APROBACION', 'VIGENTE', 'RECHAZADA')"
    )
