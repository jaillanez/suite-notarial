"""fase0_base

Revision ID: 3fb6a96d0533
Revises: 
Create Date: 2026-10-25 10:18:59.870779

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '3fb6a96d0533'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Base limpia: solo garantiza pgcrypto para gen_random_uuid()."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade() -> None:
    """No se elimina pgcrypto: puede ser usado por otros objetos de la base."""
