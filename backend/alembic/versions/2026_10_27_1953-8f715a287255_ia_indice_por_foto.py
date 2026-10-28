"""ia_indice_por_foto

Sugerencias de un nuevo tipo: cada renglón de la foto del índice del protocolo es una
sugerencia de acto (EXTRACCION_INDICE), con DDJJ y, al ratificarse, el acto creado.

El downgrade falla si ya hay sugerencias de índice: no se borran (regla INM).

Revision ID: 8f715a287255
Revises: 9999ede27a8f
Create Date: 2026-10-27 19:53:44.766004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f715a287255'
down_revision: Union[str, Sequence[str], None] = '9999ede27a8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "ia_sugerencias"
NUEVAS = {
    "tipo_valido": "tipo IN ('EXTRACCION_MINUTA', 'OCR_DNI', 'EXTRACCION_INDICE')",
    "minuta_ddjj": "tipo = 'OCR_DNI' OR ddjj_id IS NOT NULL",
    "acto_de_minuta": "tipo IN ('EXTRACCION_MINUTA', 'EXTRACCION_INDICE') OR acto_id IS NULL",
}
ANTERIORES = {
    "tipo_valido": "tipo IN ('EXTRACCION_MINUTA', 'OCR_DNI')",
    "minuta_ddjj": "tipo <> 'EXTRACCION_MINUTA' OR ddjj_id IS NOT NULL",
    "acto_de_minuta": "tipo = 'EXTRACCION_MINUTA' OR acto_id IS NULL",
}


def _reemplazar(checks: dict[str, str]) -> None:
    for nombre, condicion in checks.items():
        op.drop_constraint(op.f(f"ck_{TABLA}_{nombre}"), TABLA, type_="check")
        op.create_check_constraint(op.f(f"ck_{TABLA}_{nombre}"), TABLA, condicion)


def upgrade() -> None:
    """Upgrade schema."""
    _reemplazar(NUEVAS)


def downgrade() -> None:
    """Downgrade schema."""
    _reemplazar(ANTERIORES)
