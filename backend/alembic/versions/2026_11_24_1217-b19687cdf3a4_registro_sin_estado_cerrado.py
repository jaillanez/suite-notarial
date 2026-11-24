"""registro_sin_estado_cerrado: «cerrado» y «vacante» son lo mismo

Respuesta de la Caja (Horacio Quiroga, 24/11/2026): un registro sin titular no funciona, esté
«cerrado» o «vacante»; vuelve a funcionar cuando el gobierno nombra un titular. Los registros
cerrados pasan a VACANTE y el estado CERRADO deja de existir.

Revision ID: b19687cdf3a4
Revises: 75a529716069
Create Date: 2026-11-24

"""

from typing import Sequence, Union

from alembic import op

revision: str = "b19687cdf3a4"
down_revision: Union[str, Sequence[str], None] = "75a529716069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "padron_registros_notariales"
NOMBRE = op.f("ck_padron_registros_notariales_estado_valido")


def upgrade() -> None:
    op.execute(f"UPDATE {TABLA} SET estado = 'VACANTE' WHERE estado = 'CERRADO'")
    op.drop_constraint(NOMBRE, TABLA, type_="check")
    op.create_check_constraint(NOMBRE, TABLA, "estado IN ('ACTIVO', 'VACANTE')")


def downgrade() -> None:
    # Los que eran CERRADO quedan VACANTE: la Caja confirmó que es lo mismo.
    op.drop_constraint(NOMBRE, TABLA, type_="check")
    op.create_check_constraint(NOMBRE, TABLA, "estado IN ('ACTIVO', 'VACANTE', 'CERRADO')")
