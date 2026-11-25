"""ddjj_original_vale_hasta_rectificativa: la original vale hasta presentar la rectificativa

Observación de la Caja (Horacio Quiroga, 25/11/2026): mientras la rectificativa no esté
presentada, la DDJJ original no queda rectificada. Durante ese tiempo conviven la original
PRESENTADA y la rectificativa en BORRADOR, así que el índice «una sola DDJJ en curso» se parte
en dos: una sola presentada y un solo borrador por registro y período.

Revision ID: 511b1dfdec69
Revises: f8dcea425a4d
Create Date: 2026-11-25

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "511b1dfdec69"
down_revision: Union[str, Sequence[str], None] = "f8dcea425a4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "ddjj_declaraciones"
VIGENTE = op.f("uq_ddjj_declaraciones_registro_periodo_vigente")
PRESENTADA = "uq_ddjj_declaraciones_registro_periodo_presentada"
BORRADOR = "uq_ddjj_declaraciones_registro_periodo_borrador"


def upgrade() -> None:
    op.drop_index(VIGENTE, table_name=TABLA)
    op.create_index(
        BORRADOR,
        TABLA,
        ["registro_id", "periodo"],
        unique=True,
        postgresql_where=sa.text("estado = 'BORRADOR'"),
    )
    op.create_index(
        PRESENTADA,
        TABLA,
        ["registro_id", "periodo"],
        unique=True,
        postgresql_where=sa.text("estado = 'PRESENTADA'"),
    )


def downgrade() -> None:
    # Como antes: la original con una rectificativa abierta queda rectificada y sus boletas
    # pendientes, anuladas (si no, no entra en el índice de una sola DDJJ en curso).
    op.execute(
        f"""
        UPDATE ddjj_boletas b SET estado = 'ANULADA', anulada_en = now(),
               motivo_anulacion = 'DDJJ en rectificación.'
          FROM {TABLA} o
         WHERE b.ddjj_id = o.id AND b.estado = 'PENDIENTE' AND o.estado = 'PRESENTADA'
           AND EXISTS (SELECT 1 FROM {TABLA} r
                        WHERE r.rectifica_a_id = o.id AND r.estado = 'BORRADOR')
        """
    )
    op.execute(
        f"""
        UPDATE {TABLA} o SET estado = 'RECTIFICADA'
         WHERE o.estado = 'PRESENTADA'
           AND EXISTS (SELECT 1 FROM {TABLA} r
                        WHERE r.rectifica_a_id = o.id AND r.estado = 'BORRADOR')
        """
    )
    op.drop_index(PRESENTADA, table_name=TABLA)
    op.drop_index(BORRADOR, table_name=TABLA)
    op.create_index(
        VIGENTE,
        TABLA,
        ["registro_id", "periodo"],
        unique=True,
        postgresql_where=sa.text("estado <> 'RECTIFICADA'"),
    )
