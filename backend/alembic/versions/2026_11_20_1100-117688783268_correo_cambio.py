"""correo_cambio: pedidos de cambio del correo de ingreso desde Mi cuenta

Pedido de la Caja (Horacio Quiroga, 20/11/2026): el escribano puede cambiar su correo. El
cambio se confirma con un enlace de un solo uso enviado a la dirección nueva.

Revision ID: 117688783268
Revises: e3a7b8c9d0f1
Create Date: 2026-11-20 11:37:10.008545

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "117688783268"
down_revision: Union[str, Sequence[str], None] = "e3a7b8c9d0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "security_email_change_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("nuevo_email", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by_ip", postgresql.INET(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "nuevo_email = lower(nuevo_email)",
            name=op.f("ck_security_email_change_tokens_email_lowercase"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["security_users.id"],
            name=op.f("fk_security_email_change_tokens_user_id_security_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_email_change_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_security_email_change_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_security_email_change_tokens_user_id"),
        "security_email_change_tokens",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_security_email_change_tokens_user_id"), table_name="security_email_change_tokens"
    )
    op.drop_table("security_email_change_tokens")
