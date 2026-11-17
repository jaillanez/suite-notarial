"""avisos_supervielle_generacion: contador de avisos sin consultar

`pagos_supervielle.aviso_generacion` sube con cada aviso que llega sin poder consultarse; la marca
de aviso pendiente se borra solo si la generación no cambió mientras se consultaba. Así la hora
de la marca queda fija en la del aviso más viejo (nadie la corre hacia adelante).

Revision ID: b9d4e5f6a7c8
Revises: a8c3d4e5f6b7
Create Date: 2026-11-17 21:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9d4e5f6a7c8"
down_revision: Union[str, None] = "a8c3d4e5f6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pagos_supervielle",
        sa.Column("aviso_generacion", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("pagos_supervielle", "aviso_generacion")
