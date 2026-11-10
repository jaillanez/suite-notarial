"""boletas_por_notario: una boleta por escribano y forma de aporte del escribano a cargo

Contrato con la Caja (Anexo I): cada notario del registro (titular, adscripto, a cargo) paga su
boleta en forma independiente.

- `ddjj_boletas.escribano_id`, `cargo` y `modalidad` (COMPLETA, CON_MINIMO, SOLO_ACTOS): de quién
  es la boleta y qué cobra, congelados al emitir. Las boletas ya emitidas eran del registro y
  quedan con los tres vacíos (no se tocan: regla SNAP).
- La boleta pendiente pasa a ser una por escribano y DDJJ (`NULLS NOT DISTINCT`: las del registro
  siguen contando como una).
- Los tres datos nuevos no cambian después de emitida la boleta (trigger propio: el de
  fase4_ddjj_boletas enumera las columnas de entonces).
- `padron_designaciones_a_cargo.aporte` (SOLO_ACTOS, EN_BOLETA_DEL_TITULAR, CON_MINIMO): qué paga
  quien está a cargo por los actos del registro. La fija la Caja caso por caso; las designaciones
  existentes quedan en SOLO_ACTOS.

Revision ID: d5b1e7a3c904
Revises: a8105b477314
Create Date: 2026-11-09 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5b1e7a3c904"
down_revision: Union[str, None] = "a8105b477314"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GUARD_FN = """
CREATE OR REPLACE FUNCTION ddjj_boletas_escribano_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.escribano_id, NEW.cargo, NEW.modalidad)
       IS DISTINCT FROM (OLD.escribano_id, OLD.cargo, OLD.modalidad) THEN
        RAISE EXCEPTION 'ddjj_boletas: el escribano de una boleta emitida no cambia'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.add_column("ddjj_boletas", sa.Column("escribano_id", sa.UUID(), nullable=True))
    op.add_column("ddjj_boletas", sa.Column("cargo", sa.String(length=30), nullable=True))
    op.add_column("ddjj_boletas", sa.Column("modalidad", sa.String(length=20), nullable=True))
    op.create_foreign_key(
        op.f("fk_ddjj_boletas_escribano_id_padron_escribanos"),
        "ddjj_boletas",
        "padron_escribanos",
        ["escribano_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_ddjj_boletas_escribano_id"), "ddjj_boletas", ["escribano_id"], unique=False
    )
    op.create_check_constraint(
        op.f("ck_ddjj_boletas_escribano_completo"),
        "ddjj_boletas",
        "(escribano_id IS NULL) = (cargo IS NULL) AND (escribano_id IS NULL) = (modalidad IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_ddjj_boletas_modalidad_valida"),
        "ddjj_boletas",
        "modalidad IS NULL OR modalidad IN ('COMPLETA', 'CON_MINIMO', 'SOLO_ACTOS')",
    )
    op.create_check_constraint(
        op.f("ck_ddjj_boletas_medico_solo_completa"),
        "ddjj_boletas",
        "modalidad IS NULL OR modalidad = 'COMPLETA' OR aporte_medico = 0",
    )
    op.create_check_constraint(
        op.f("ck_ddjj_boletas_solo_actos_sin_minimo"),
        "ddjj_boletas",
        "modalidad IS DISTINCT FROM 'SOLO_ACTOS' OR aporte_minimo = 0",
    )
    op.drop_index(
        "uq_ddjj_boletas_pendiente",
        table_name="ddjj_boletas",
        postgresql_where=sa.text("estado = 'PENDIENTE'"),
    )
    op.create_index(
        "uq_ddjj_boletas_pendiente",
        "ddjj_boletas",
        ["ddjj_id", "escribano_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'PENDIENTE'"),
        postgresql_nulls_not_distinct=True,
    )
    op.execute(GUARD_FN)
    op.execute(
        "CREATE TRIGGER ddjj_boletas_escribano_guard BEFORE UPDATE ON ddjj_boletas "
        "FOR EACH ROW EXECUTE FUNCTION ddjj_boletas_escribano_guard()"
    )

    op.add_column(
        "padron_designaciones_a_cargo",
        sa.Column("aporte", sa.String(length=30), server_default="SOLO_ACTOS", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_padron_designaciones_a_cargo_aporte_valido"),
        "padron_designaciones_a_cargo",
        "aporte IN ('SOLO_ACTOS', 'EN_BOLETA_DEL_TITULAR', 'CON_MINIMO')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_padron_designaciones_a_cargo_aporte_valido"),
        "padron_designaciones_a_cargo",
        type_="check",
    )
    op.drop_column("padron_designaciones_a_cargo", "aporte")

    op.execute("DROP TRIGGER IF EXISTS ddjj_boletas_escribano_guard ON ddjj_boletas")
    op.execute("DROP FUNCTION IF EXISTS ddjj_boletas_escribano_guard()")
    op.drop_index(
        "uq_ddjj_boletas_pendiente",
        table_name="ddjj_boletas",
        postgresql_where=sa.text("estado = 'PENDIENTE'"),
    )
    # Volver a una pendiente por DDJJ solo es posible si no hay boletas por notario emitidas.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM ddjj_boletas WHERE escribano_id IS NOT NULL) THEN
                RAISE EXCEPTION 'Hay boletas por notario emitidas: no se puede volver atrás';
            END IF;
        END;
        $$;
        """
    )
    op.create_index(
        "uq_ddjj_boletas_pendiente",
        "ddjj_boletas",
        ["ddjj_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'PENDIENTE'"),
    )
    for nombre in (
        "solo_actos_sin_minimo",
        "medico_solo_completa",
        "modalidad_valida",
        "escribano_completo",
    ):
        op.drop_constraint(op.f(f"ck_ddjj_boletas_{nombre}"), "ddjj_boletas", type_="check")
    op.drop_index(op.f("ix_ddjj_boletas_escribano_id"), table_name="ddjj_boletas")
    op.drop_constraint(
        op.f("fk_ddjj_boletas_escribano_id_padron_escribanos"), "ddjj_boletas", type_="foreignkey"
    )
    op.drop_column("ddjj_boletas", "modalidad")
    op.drop_column("ddjj_boletas", "cargo")
    op.drop_column("ddjj_boletas", "escribano_id")
