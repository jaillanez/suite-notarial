"""histórico de boletas: registro «a completar» con asignación única y auditada

El origen tiene aportes pagados sin el registro y sin forma de deducirlo. Se migran igual con el
nombre de quien pagó (`escribano_origen`) y la Caja les asigna el registro después, una sola vez.

Revision ID: d4e9f0a1b2c3
Revises: c3d8e1f2a4b6
Create Date: 2026-11-12 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e9f0a1b2c3"
down_revision: str | None = "c3d8e1f2a4b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "historico_boletas"

# migracion_guard() de la revisión c3a9d5e7f214 más una única excepción: una boleta histórica
# migrada sin registro admite UNA actualización que solo le asigna el registro y quién y cuándo
# lo hizo. Todo lo demás del histórico sigue sin modificarse ni borrarse.
GUARD_FN = """
CREATE OR REPLACE FUNCTION migracion_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION '%: la migración no se borra (trazabilidad)', TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_TABLE_NAME IN ('historico_boletas', 'historico_pagos', 'historico_creditos') THEN
        IF TG_OP = 'INSERT' THEN
            IF coalesce(current_setting('suite.migracion', true), '') <> 'on' THEN
                RAISE EXCEPTION '%: el histórico solo se carga desde la migración', TG_TABLE_NAME
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END IF;
        {excepcion}
        RAISE EXCEPTION '%: el histórico del sistema anterior no se modifica', TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_TABLE_NAME = 'migracion_corridas' THEN
        IF OLD.estado <> 'EN_CURSO' THEN
            RAISE EXCEPTION 'migracion_corridas: una corrida cerrada no se modifica'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id
            OR NEW.modo IS DISTINCT FROM OLD.modo
            OR NEW.huella_lote IS DISTINCT FROM OLD.huella_lote
            OR NEW.version_formato IS DISTINCT FROM OLD.version_formato
            OR NEW.homologacion IS DISTINCT FROM OLD.homologacion
            OR NEW.homologacion_ejemplo IS DISTINCT FROM OLD.homologacion_ejemplo
            OR NEW.huella_homologacion IS DISTINCT FROM OLD.huella_homologacion
            OR NEW.homologacion_tablas IS DISTINCT FROM OLD.homologacion_tablas
            OR NEW.operador_user_id IS DISTINCT FROM OLD.operador_user_id
            OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'migracion_corridas: la identidad de la corrida no se modifica'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION '%: no se modifica', TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END
$$;
"""
ASIGNACION = """
        IF TG_TABLE_NAME = 'historico_boletas' THEN
            IF OLD.registro_id IS NULL AND NEW.registro_id IS NOT NULL
                AND NEW.registro_asignado_por_user_id IS NOT NULL
                AND NEW.registro_asignado_en IS NOT NULL
                AND (to_jsonb(NEW) - 'registro_id' - 'registro_asignado_por_user_id'
                     - 'registro_asignado_en')
                    = (to_jsonb(OLD) - 'registro_id' - 'registro_asignado_por_user_id'
                       - 'registro_asignado_en') THEN
                RETURN NEW;
            END IF;
        END IF;"""


def upgrade() -> None:
    op.alter_column(TABLA, "registro_id", existing_type=sa.UUID(), nullable=True)
    op.add_column(TABLA, sa.Column("escribano_origen", sa.String(length=200), nullable=True))
    op.add_column(
        TABLA, sa.Column("registro_asignado_por_user_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        TABLA, sa.Column("registro_asignado_en", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_historico_boletas_registro_asignado_por_user_id_security_users"),
        TABLA,
        "security_users",
        ["registro_asignado_por_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_historico_boletas_registro_o_escribano"),
        TABLA,
        "registro_id IS NOT NULL OR escribano_origen IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_historico_boletas_asignacion_completa"),
        TABLA,
        "(registro_asignado_por_user_id IS NULL) = (registro_asignado_en IS NULL)",
    )
    op.execute(GUARD_FN.replace("{excepcion}", ASIGNACION))


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {TABLA} WHERE registro_id IS NULL) THEN
                RAISE EXCEPTION 'Hay boletas históricas sin registro: asignalo antes de volver '
                    'atrás esta migración.';
            END IF;
        END $$;
        """
    )
    op.execute(GUARD_FN.replace("{excepcion}", ""))
    op.drop_constraint(
        op.f("ck_historico_boletas_asignacion_completa"), TABLA, type_="check"
    )
    op.drop_constraint(op.f("ck_historico_boletas_registro_o_escribano"), TABLA, type_="check")
    op.drop_constraint(
        op.f("fk_historico_boletas_registro_asignado_por_user_id_security_users"),
        TABLA,
        type_="foreignkey",
    )
    op.drop_column(TABLA, "registro_asignado_en")
    op.drop_column(TABLA, "registro_asignado_por_user_id")
    op.drop_column(TABLA, "escribano_origen")
    op.alter_column(TABLA, "registro_id", existing_type=sa.UUID(), nullable=False)
