"""cms_informe_actuarial: los informes actuariales como tipo de documento oficial

Anexo I: el sitio institucional publica estados contables, informes actuariales, etc.

Revision ID: ab95fae36072
Revises: b91e9ed70397
Create Date: 2026-11-10 12:06:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "ab95fae36072"
down_revision: str | None = "b91e9ed70397"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "cms_documentos"
NOMBRE = "ck_cms_documentos_tipo"
ANTES = "tipo IN ('ESTADO_CONTABLE', 'MEMORIA_ANUAL', 'RESOLUCION', 'OTRO')"
AHORA = "tipo IN ('ESTADO_CONTABLE', 'MEMORIA_ANUAL', 'INFORME_ACTUARIAL', 'RESOLUCION', 'OTRO')"


def upgrade() -> None:
    op.drop_constraint(op.f(NOMBRE), TABLA, type_="check")
    op.create_check_constraint(op.f(NOMBRE), TABLA, AHORA)


def downgrade() -> None:
    # Falla si ya hay informes actuariales cargados: los documentos no se borran ni cambian de
    # tipo (regla INM), así que no hay forma segura de volver atrás con datos.
    op.drop_constraint(op.f(NOMBRE), TABLA, type_="check")
    op.create_check_constraint(op.f(NOMBRE), TABLA, ANTES)
