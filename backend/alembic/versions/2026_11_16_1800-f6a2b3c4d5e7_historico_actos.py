"""historico_actos: cada acto de las DDJJ presentadas en el sistema anterior

El sistema anterior (la web de la Caja) guarda cada acto declarado, uno por renglón, con su
protocolo, escritura, folio, naturaleza, base y aporte repartido entre titular, adscripto y a
cargo. Es la DDJJ «por acto» del Anexo I. Se migra desde `actos.csv` (agregado opcional al
formato v2) a un histórico de solo lectura, como boletas, pagos y créditos. Es consulta: no
entra en los saldos.

Revision ID: f6a2b3c4d5e7
Revises: e5f1a2b3c4d6
Create Date: 2026-11-16 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a2b3c4d5e7"
down_revision: str | None = "e5f1a2b3c4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "historico_actos"

# migracion_guard() de la revisión d4e9f0a1b2c3 (con la asignación única del registro de una
# boleta histórica) y el histórico de actos agregado a las tablas de solo lectura.
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


HISTORICOS_ANTES = "'historico_boletas', 'historico_pagos', 'historico_creditos'"
HISTORICOS_AHORA = "'historico_boletas', 'historico_pagos', 'historico_creditos', 'historico_actos'"


def _guard(historicos: str) -> str:
    return GUARD_FN.replace("{historicos}", historicos).replace("{excepcion}", ASIGNACION)


def _monto(nombre: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(nombre, sa.Numeric(precision=15, scale=2), nullable=True)


def upgrade() -> None:
    op.create_table(
        TABLA,
        sa.Column("corrida_id", sa.UUID(), nullable=False),
        sa.Column("codigo_legado", sa.String(length=100), nullable=False),
        sa.Column("declaracion_legado", sa.String(length=100), nullable=True),
        sa.Column("registro_id", sa.UUID(), nullable=False),
        sa.Column("escribano_id", sa.UUID(), nullable=True),
        sa.Column("escribano_origen", sa.String(length=200), nullable=True),
        sa.Column("cargo", sa.String(length=20), nullable=True),
        sa.Column("periodo", sa.String(length=7), nullable=False),
        sa.Column("fecha_acto", sa.Date(), nullable=True),
        sa.Column("tipo_protocolo", sa.String(length=20), nullable=True),
        sa.Column("numero_escritura", sa.Integer(), nullable=False),
        sa.Column("folio", sa.Integer(), nullable=True),
        sa.Column("naturaleza", sa.String(length=500), nullable=False),
        sa.Column("exento", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _monto("base_imponible"),
        _monto("aporte_variable"),
        _monto("aporte_fijo"),
        _monto("aporte_titular"),
        _monto("aporte_adscripto"),
        _monto("aporte_a_cargo"),
        sa.Column("importe", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint("importe >= 0", name=op.f("ck_historico_actos_importe")),
        sa.CheckConstraint(
            "coalesce(base_imponible, 0) >= 0 AND coalesce(aporte_variable, 0) >= 0 "
            "AND coalesce(aporte_fijo, 0) >= 0 AND coalesce(aporte_titular, 0) >= 0 "
            "AND coalesce(aporte_adscripto, 0) >= 0 AND coalesce(aporte_a_cargo, 0) >= 0",
            name=op.f("ck_historico_actos_montos_no_negativos"),
        ),
        sa.CheckConstraint(
            "tipo_protocolo IS NULL OR tipo_protocolo IN ('GENERAL', 'AUXILIAR')",
            name=op.f("ck_historico_actos_tipo_protocolo_valido"),
        ),
        sa.CheckConstraint(
            "cargo IS NULL OR cargo IN ('TITULAR', 'ADSCRIPTO', 'SUPLENTE_INTERINO')",
            name=op.f("ck_historico_actos_cargo_valido"),
        ),
        sa.ForeignKeyConstraint(
            ["corrida_id"],
            ["migracion_corridas.id"],
            name=op.f("fk_historico_actos_corrida_id_migracion_corridas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["registro_id"],
            ["padron_registros_notariales.id"],
            name=op.f("fk_historico_actos_registro_id_padron_registros_notariales"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["escribano_id"],
            ["padron_escribanos.id"],
            name=op.f("fk_historico_actos_escribano_id_padron_escribanos"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historico_actos")),
        sa.UniqueConstraint("codigo_legado", name=op.f("uq_historico_actos_codigo_legado")),
    )
    op.create_index(
        "ix_historico_actos_registro_periodo", TABLA, ["registro_id", "periodo"], unique=False
    )
    op.create_index(
        "ix_historico_actos_escribano_periodo", TABLA, ["escribano_id", "periodo"], unique=False
    )
    op.execute(_guard(HISTORICOS_AHORA))
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
    # Quitar la tabla con actos migrados perdería el histórico declarado: no se vuelve atrás.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {TABLA}) THEN
                RAISE EXCEPTION 'Hay actos del sistema anterior migrados: no se puede quitar '
                    '{TABLA}.';
            END IF;
        END;
        $$;
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {TABLA}_guard ON {TABLA}")
    op.execute(f"DROP TRIGGER IF EXISTS {TABLA}_no_truncate ON {TABLA}")
    op.drop_index("ix_historico_actos_escribano_periodo", table_name=TABLA)
    op.drop_index("ix_historico_actos_registro_periodo", table_name=TABLA)
    op.drop_table(TABLA)
    op.execute(_guard(HISTORICOS_ANTES))
