"""pagos_supervielle: pago de boletas con el botón de pagos Supervielle

- `pagos_supervielle`: cada deuda publicada en el banco y el pago que informa (sin borrado). Los
  datos de la publicación no cambian; el estado se actualiza con lo que informa la API.
- `pagos_supervielle_publicacion_seq`: numera las publicaciones (el banco pide un
  `id_publicacion` numérico que no se repita).
- `pagos_comprobantes.origen` admite SUPERVIELLE: el pago aprobado entra a la mesa de Tesorería.
- Motor paramétrico: tipo COMISION_COBRO (porcentaje sobre lo cobrado, con mínimo y tope), para
  que la Caja administre las comisiones del banco. Cada pago guarda las vigencias con que se
  estimó su comisión.

Revision ID: a8c3d4e5f6b7
Revises: f6a2b3c4d5e7
Create Date: 2026-11-17 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8c3d4e5f6b7"
down_revision: Union[str, None] = "f6a2b3c4d5e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SPV = "pagos_supervielle"
SECUENCIA = "pagos_supervielle_publicacion_seq"
ORIGEN_ANTERIOR = "origen IN ('ARCHIVO', 'MERCADO_PAGO')"
ORIGEN = "origen IN ('ARCHIVO', 'MERCADO_PAGO', 'SUPERVIELLE')"
TIPOS_ANTES = (
    "'PORCENTUAL_ACTO', 'FIJO_ACTO', 'FIJO_MENSUAL', 'TASA_MORA', 'CRITERIO_PLURALIDAD'"
)
TIPOS = TIPOS_ANTES + ", 'COMISION_COBRO'"

# La boleta, la publicación, lo publicado y quién la inició no cambian; el comprobante, una vez
# asignado, tampoco. Nada se borra (regla INM).
SPV_GUARD_FN = """
CREATE OR REPLACE FUNCTION pagos_supervielle_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION '%: % no permitido (sin borrado físico, regla INM)', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF (NEW.id, NEW.boleta_id, NEW.id_publicacion, NEW.hash, NEW.link_pago, NEW.importe_boleta,
        NEW.vence, NEW.iniciado_por_user_id, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.boleta_id, OLD.id_publicacion, OLD.hash, OLD.link_pago, OLD.importe_boleta,
        OLD.vence, OLD.iniciado_por_user_id, OLD.created_at)
       OR (OLD.comprobante_id IS NOT NULL AND NEW.comprobante_id IS DISTINCT FROM OLD.comprobante_id)
    THEN
        RAISE EXCEPTION 'pagos_supervielle: los datos de la publicación no se modifican'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;
"""


def _revoke_from_app_roles(table: str, privileges: str) -> None:
    op.execute(
        f"""
        DO $$
        DECLARE grantee_name text;
        BEGIN
            FOR grantee_name IN
                SELECT DISTINCT grantee FROM information_schema.role_table_grants
                WHERE table_schema = 'public' AND table_name = '{table}'
                  AND grantee <> current_user
            LOOP
                EXECUTE format('REVOKE {privileges} ON {table} FROM %I', grantee_name);
            END LOOP;
        END
        $$;
        """
    )


def upgrade() -> None:
    op.execute(f"CREATE SEQUENCE {SECUENCIA} AS bigint START WITH 1000")
    op.create_table(
        SPV,
        sa.Column("boleta_id", sa.UUID(), nullable=False),
        sa.Column("id_publicacion", sa.BigInteger(), nullable=False),
        sa.Column("hash", sa.String(length=100), nullable=False),
        sa.Column("link_pago", sa.String(length=500), nullable=False),
        sa.Column("importe_boleta", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("vence", sa.Date(), nullable=False),
        sa.Column("iniciado_por_user_id", sa.UUID(), nullable=False),
        sa.Column("estado", sa.String(length=20), server_default="CREADO", nullable=False),
        sa.Column("spv_pago_id", sa.String(length=50), nullable=True),
        sa.Column("medio_pago", sa.String(length=50), nullable=True),
        sa.Column("importe_pagado", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("pagado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comision_estimada", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column("vigencia_comision_boton_id", sa.UUID(), nullable=True),
        sa.Column("vigencia_comision_medio_id", sa.UUID(), nullable=True),
        sa.Column("consultado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aviso_pendiente_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comprobante_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "estado IN ('CREADO', 'APROBADO', 'ACREDITADO', 'PENDIENTE', 'REVERSADO', 'ANULADO')",
            name=op.f("ck_pagos_supervielle_estado_valido"),
        ),
        sa.CheckConstraint("importe_boleta > 0", name=op.f("ck_pagos_supervielle_importe_boleta")),
        sa.CheckConstraint(
            "estado = 'CREADO' OR spv_pago_id IS NOT NULL",
            name=op.f("ck_pagos_supervielle_pago_informado"),
        ),
        sa.ForeignKeyConstraint(
            ["boleta_id"],
            ["ddjj_boletas.id"],
            name=op.f("fk_pagos_supervielle_boleta_id_ddjj_boletas"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["comprobante_id"],
            ["pagos_comprobantes.id"],
            name=op.f("fk_pagos_supervielle_comprobante_id_pagos_comprobantes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vigencia_comision_boton_id"],
            ["parametros_vigencias.id"],
            name=op.f("fk_pagos_supervielle_vigencia_comision_boton_id_parametros_vigencias"),
        ),
        sa.ForeignKeyConstraint(
            ["vigencia_comision_medio_id"],
            ["parametros_vigencias.id"],
            name=op.f("fk_pagos_supervielle_vigencia_comision_medio_id_parametros_vigencias"),
        ),
        sa.ForeignKeyConstraint(
            ["iniciado_por_user_id"],
            ["security_users.id"],
            name=op.f("fk_pagos_supervielle_iniciado_por_user_id_security_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pagos_supervielle")),
        sa.UniqueConstraint("comprobante_id", name=op.f("uq_pagos_supervielle_comprobante_id")),
        sa.UniqueConstraint("hash", name=op.f("uq_pagos_supervielle_hash")),
        sa.UniqueConstraint("id_publicacion", name=op.f("uq_pagos_supervielle_id_publicacion")),
        sa.UniqueConstraint("spv_pago_id", name=op.f("uq_pagos_supervielle_spv_pago_id")),
    )
    op.create_index(op.f("ix_pagos_supervielle_boleta_id"), SPV, ["boleta_id"], unique=False)
    op.drop_constraint(
        op.f("ck_pagos_comprobantes_origen_valido"), "pagos_comprobantes", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_pagos_comprobantes_origen_valido"), "pagos_comprobantes", ORIGEN
    )
    op.drop_constraint(
        op.f("ck_parametros_conceptos_tipo_valido"), "parametros_conceptos", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_parametros_conceptos_tipo_valido"), "parametros_conceptos", f"tipo IN ({TIPOS})"
    )
    op.execute(SPV_GUARD_FN)
    _revoke_from_app_roles(SPV, "DELETE, TRUNCATE")
    op.execute(
        f"CREATE TRIGGER {SPV}_guard BEFORE UPDATE OR DELETE ON {SPV} "
        "FOR EACH ROW EXECUTE FUNCTION pagos_supervielle_guard()"
    )
    op.execute(
        f"CREATE TRIGGER {SPV}_no_truncate BEFORE TRUNCATE ON {SPV} "
        "FOR EACH STATEMENT EXECUTE FUNCTION pagos_supervielle_guard()"
    )


def downgrade() -> None:
    """Falla si ya hay deudas publicadas en el banco (no se borran)."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pagos_supervielle)
               OR EXISTS (SELECT 1 FROM pagos_comprobantes WHERE origen = 'SUPERVIELLE') THEN
                RAISE EXCEPTION 'Hay pagos con el botón Supervielle: no se puede volver atrás';
            END IF;
            IF EXISTS (SELECT 1 FROM parametros_conceptos WHERE tipo = 'COMISION_COBRO') THEN
                RAISE EXCEPTION 'Hay conceptos de comisión de cobro: no se puede volver atrás';
            END IF;
        END;
        $$;
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {SPV}_no_truncate ON {SPV}")
    op.execute(f"DROP TRIGGER IF EXISTS {SPV}_guard ON {SPV}")
    op.execute("DROP FUNCTION IF EXISTS pagos_supervielle_guard()")
    op.drop_constraint(
        op.f("ck_parametros_conceptos_tipo_valido"), "parametros_conceptos", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_parametros_conceptos_tipo_valido"),
        "parametros_conceptos",
        f"tipo IN ({TIPOS_ANTES})",
    )
    op.drop_constraint(
        op.f("ck_pagos_comprobantes_origen_valido"), "pagos_comprobantes", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_pagos_comprobantes_origen_valido"), "pagos_comprobantes", ORIGEN_ANTERIOR
    )
    op.drop_index(op.f("ix_pagos_supervielle_boleta_id"), table_name=SPV)
    op.drop_table(SPV)
    op.execute(f"DROP SEQUENCE IF EXISTS {SECUENCIA}")
