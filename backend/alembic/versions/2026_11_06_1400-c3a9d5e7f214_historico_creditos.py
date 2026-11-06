"""historico_creditos: créditos a favor del escribano en el sistema anterior

En el libro de pagos de la Caja los importes negativos son créditos a favor del escribano (casi
todos diferencias de inspección: pagó de más). Se migran desde `creditos.csv` (agregado
opcional al formato v2) a un histórico de solo lectura, como boletas y pagos, y restan del
saldo del registro.

TODO(negocio): decidir si el saldo a favor del sistema anterior se aplica a boletas nuevas.

Revision ID: c3a9d5e7f214
Revises: b8f61c8f2577
Create Date: 2026-11-06 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3a9d5e7f214"
down_revision: str | None = "b8f61c8f2577"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "historico_creditos"

# migracion_guard() de la revisión 498149192f66 con el histórico de créditos agregado: solo
# admite INSERT dentro de una carga (SET LOCAL suite.migracion = 'on') y nunca se modifica ni se
# borra. En plpgsql AND no corta en cortocircuito: cada tabla en su IF anidado.
GUARD_FN = """
CREATE OR REPLACE FUNCTION migracion_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION '%: la migración no se borra (trazabilidad)', TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_TABLE_NAME IN ({historicos}) THEN
        IF TG_OP = 'INSERT' THEN
            IF coalesce(current_setting('suite.migracion', true), '') <> 'on' THEN
                RAISE EXCEPTION '%: el histórico solo se carga desde la migración', TG_TABLE_NAME
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END IF;
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
HISTORICOS_ANTES = "'historico_boletas', 'historico_pagos'"
HISTORICOS_AHORA = "'historico_boletas', 'historico_pagos', 'historico_creditos'"


def upgrade() -> None:
    op.create_table(
        TABLA,
        sa.Column("corrida_id", sa.UUID(), nullable=False),
        sa.Column("codigo_legado", sa.String(length=100), nullable=False),
        sa.Column("registro_id", sa.UUID(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("periodo", sa.String(length=7), nullable=True),
        sa.Column("importe", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("concepto", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint("importe > 0", name=op.f("ck_historico_creditos_importe")),
        sa.ForeignKeyConstraint(
            ["corrida_id"],
            ["migracion_corridas.id"],
            name=op.f("fk_historico_creditos_corrida_id_migracion_corridas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["registro_id"],
            ["padron_registros_notariales.id"],
            name=op.f("fk_historico_creditos_registro_id_padron_registros_notariales"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historico_creditos")),
        sa.UniqueConstraint("codigo_legado", name=op.f("uq_historico_creditos_codigo_legado")),
    )
    op.create_index(
        "ix_historico_creditos_registro_fecha", TABLA, ["registro_id", "fecha"], unique=False
    )
    op.execute(GUARD_FN.replace("{historicos}", HISTORICOS_AHORA))
    # Como el resto del histórico: la aplicación no borra ni vacía (además del trigger).
    op.execute(
        f"""
        DO $$
        DECLARE grantee_name text;
        BEGIN
            FOR grantee_name IN
                SELECT DISTINCT grantee FROM information_schema.role_table_grants
                WHERE table_schema = 'public' AND table_name = '{TABLA}'
                  AND grantee <> current_user
            LOOP
                EXECUTE format('REVOKE DELETE, TRUNCATE ON {TABLA} FROM %I', grantee_name);
            END LOOP;
        END
        $$;
        """
    )
    op.execute(
        f"CREATE TRIGGER {TABLA}_guard BEFORE INSERT OR UPDATE OR DELETE ON {TABLA} "
        "FOR EACH ROW EXECUTE FUNCTION migracion_guard()"
    )
    op.execute(
        f"CREATE TRIGGER {TABLA}_no_truncate BEFORE TRUNCATE ON {TABLA} "
        "FOR EACH STATEMENT EXECUTE FUNCTION migracion_guard()"
    )


def downgrade() -> None:
    # Quitar la tabla con créditos migrados perdería saldos a favor: no se vuelve atrás.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {TABLA}) THEN
                RAISE EXCEPTION 'Hay créditos del sistema anterior migrados: no se puede quitar '
                    '{TABLA}.';
            END IF;
        END;
        $$;
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {TABLA}_guard ON {TABLA}")
    op.execute(f"DROP TRIGGER IF EXISTS {TABLA}_no_truncate ON {TABLA}")
    op.drop_index("ix_historico_creditos_registro_fecha", table_name=TABLA)
    op.drop_table(TABLA)
    op.execute(GUARD_FN.replace("{historicos}", HISTORICOS_ANTES))
