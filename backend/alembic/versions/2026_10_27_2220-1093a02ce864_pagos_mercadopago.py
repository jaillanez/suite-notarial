"""pagos_mercadopago

Revision ID: 1093a02ce864
Revises: 8f715a287255
Create Date: 2026-10-27 22:20:05.353884

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# El guard de comprobantes (fase5) suma el origen a los datos que no cambian al revisar.
GUARD_FN_ANTERIOR = """
CREATE OR REPLACE FUNCTION pagos_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION '%: % no permitido (sin borrado físico, regla INM)', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- plpgsql no corta la evaluación de AND: cada tabla en su propio IF.
    IF TG_TABLE_NAME = 'pagos_conciliaciones' THEN
        RAISE EXCEPTION 'pagos_conciliaciones: un asiento de conciliación no se modifica'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_TABLE_NAME = 'pagos_comprobantes' THEN
        -- Solo se revisa una vez: de PENDIENTE_REVISION a APROBADO o RECHAZADO, sin tocar el
        -- archivo ni lo declarado por el escribano.
        IF OLD.estado <> 'PENDIENTE_REVISION'
           OR (NEW.id, NEW.boleta_id, NEW.registro_id, NEW.periodo, NEW.nombre_original,
               NEW.archivo, NEW.mime_type, NEW.tamano_bytes, NEW.sha256,
               NEW.fecha_transferencia, NEW.banco_origen, NEW.numero_operacion,
               NEW.importe_declarado, NEW.subido_por_user_id, NEW.created_at)
              IS DISTINCT FROM
              (OLD.id, OLD.boleta_id, OLD.registro_id, OLD.periodo, OLD.nombre_original,
               OLD.archivo, OLD.mime_type, OLD.tamano_bytes, OLD.sha256,
               OLD.fecha_transferencia, OLD.banco_origen, OLD.numero_operacion,
               OLD.importe_declarado, OLD.subido_por_user_id, OLD.created_at) THEN
            RAISE EXCEPTION 'pagos_comprobantes: un comprobante revisado no se modifica'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""
GUARD_FN = """
CREATE OR REPLACE FUNCTION pagos_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION '%: % no permitido (sin borrado físico, regla INM)', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- plpgsql no corta la evaluación de AND: cada tabla en su propio IF.
    IF TG_TABLE_NAME = 'pagos_conciliaciones' THEN
        RAISE EXCEPTION 'pagos_conciliaciones: un asiento de conciliación no se modifica'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_TABLE_NAME = 'pagos_comprobantes' THEN
        -- Solo se revisa una vez: de PENDIENTE_REVISION a APROBADO o RECHAZADO, sin tocar el
        -- archivo ni lo declarado por el escribano.
        IF OLD.estado <> 'PENDIENTE_REVISION'
           OR (NEW.id, NEW.boleta_id, NEW.registro_id, NEW.periodo, NEW.origen, NEW.nombre_original,
               NEW.archivo, NEW.mime_type, NEW.tamano_bytes, NEW.sha256,
               NEW.fecha_transferencia, NEW.banco_origen, NEW.numero_operacion,
               NEW.importe_declarado, NEW.subido_por_user_id, NEW.created_at)
              IS DISTINCT FROM
              (OLD.id, OLD.boleta_id, OLD.registro_id, OLD.periodo, OLD.origen, OLD.nombre_original,
               OLD.archivo, OLD.mime_type, OLD.tamano_bytes, OLD.sha256,
               OLD.fecha_transferencia, OLD.banco_origen, OLD.numero_operacion,
               OLD.importe_declarado, OLD.subido_por_user_id, OLD.created_at) THEN
            RAISE EXCEPTION 'pagos_comprobantes: un comprobante revisado no se modifica'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

# Registro de pagos con Mercado Pago: el estado se actualiza con lo que informa MP, pero la
# boleta, el cobro, el importe pedido y quién lo inició no cambian; el comprobante, una vez
# asignado, tampoco. Nada se borra (regla INM).
MP_GUARD_FN = """
CREATE OR REPLACE FUNCTION pagos_mercadopago_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION '%: % no permitido (sin borrado físico, regla INM)', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF (NEW.id, NEW.boleta_id, NEW.preference_id, NEW.importe_boleta,
        NEW.iniciado_por_user_id, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.boleta_id, OLD.preference_id, OLD.importe_boleta,
        OLD.iniciado_por_user_id, OLD.created_at)
       OR (OLD.comprobante_id IS NOT NULL AND NEW.comprobante_id IS DISTINCT FROM OLD.comprobante_id)
    THEN
        RAISE EXCEPTION 'pagos_mercadopago: los datos del cobro no se modifican'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;
"""
MP = "pagos_mercadopago"


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


# revision identifiers, used by Alembic.
revision: str = '1093a02ce864'
down_revision: Union[str, Sequence[str], None] = '8f715a287255'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('pagos_mercadopago',
    sa.Column('boleta_id', sa.UUID(), nullable=False),
    sa.Column('preference_id', sa.String(length=100), nullable=False),
    sa.Column('importe_boleta', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('iniciado_por_user_id', sa.UUID(), nullable=False),
    sa.Column('estado', sa.String(length=20), server_default='CREADO', nullable=False),
    sa.Column('mp_payment_id', sa.String(length=50), nullable=True),
    sa.Column('estado_detalle', sa.String(length=100), nullable=True),
    sa.Column('medio_pago', sa.String(length=50), nullable=True),
    sa.Column('importe_pagado', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('comision', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('importe_neto', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('aprobado_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('comprobante_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.CheckConstraint("estado = 'CREADO' OR mp_payment_id IS NOT NULL", name=op.f('ck_pagos_mercadopago_pago_informado')),
    sa.CheckConstraint("estado IN ('CREADO', 'pending', 'authorized', 'in_process', 'in_mediation', 'approved', 'rejected', 'cancelled', 'refunded', 'charged_back')", name=op.f('ck_pagos_mercadopago_estado_valido')),
    sa.CheckConstraint('importe_boleta > 0', name=op.f('ck_pagos_mercadopago_importe_boleta')),
    sa.ForeignKeyConstraint(['boleta_id'], ['ddjj_boletas.id'], name=op.f('fk_pagos_mercadopago_boleta_id_ddjj_boletas'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['comprobante_id'], ['pagos_comprobantes.id'], name=op.f('fk_pagos_mercadopago_comprobante_id_pagos_comprobantes'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['iniciado_por_user_id'], ['security_users.id'], name=op.f('fk_pagos_mercadopago_iniciado_por_user_id_security_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pagos_mercadopago')),
    sa.UniqueConstraint('comprobante_id', name=op.f('uq_pagos_mercadopago_comprobante_id')),
    sa.UniqueConstraint('mp_payment_id', name=op.f('uq_pagos_mercadopago_mp_payment_id')),
    sa.UniqueConstraint('preference_id', name=op.f('uq_pagos_mercadopago_preference_id'))
    )
    op.create_index(op.f('ix_pagos_mercadopago_boleta_id'), 'pagos_mercadopago', ['boleta_id'], unique=False)
    op.add_column('pagos_comprobantes', sa.Column('origen', sa.String(length=20), server_default='ARCHIVO', nullable=False))
    op.alter_column('pagos_comprobantes', 'nombre_original',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)
    op.alter_column('pagos_comprobantes', 'archivo',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)
    op.alter_column('pagos_comprobantes', 'mime_type',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
    op.alter_column('pagos_comprobantes', 'tamano_bytes',
               existing_type=sa.BIGINT(),
               nullable=True)
    op.alter_column('pagos_comprobantes', 'sha256',
               existing_type=sa.VARCHAR(length=64),
               nullable=True)
    # ### end Alembic commands ###
    op.create_check_constraint(
        op.f("ck_pagos_comprobantes_origen_valido"),
        "pagos_comprobantes",
        "origen IN ('ARCHIVO', 'MERCADO_PAGO')",
    )
    op.create_check_constraint(
        op.f("ck_pagos_comprobantes_archivo_segun_origen"),
        "pagos_comprobantes",
        "(origen = 'ARCHIVO') = (archivo IS NOT NULL AND nombre_original IS NOT NULL "
        "AND mime_type IS NOT NULL AND tamano_bytes IS NOT NULL AND sha256 IS NOT NULL)",
    )
    op.execute(GUARD_FN)
    op.execute(MP_GUARD_FN)
    _revoke_from_app_roles(MP, "DELETE, TRUNCATE")
    op.execute(
        f"CREATE TRIGGER {MP}_guard BEFORE UPDATE OR DELETE ON {MP} "
        "FOR EACH ROW EXECUTE FUNCTION pagos_mercadopago_guard()"
    )
    op.execute(
        f"CREATE TRIGGER {MP}_no_truncate BEFORE TRUNCATE ON {MP} "
        "FOR EACH STATEMENT EXECUTE FUNCTION pagos_mercadopago_guard()"
    )


def downgrade() -> None:
    """Downgrade schema. Falla si ya hay comprobantes de Mercado Pago (no se borran)."""
    op.execute(f"DROP TRIGGER IF EXISTS {MP}_no_truncate ON {MP}")
    op.execute(f"DROP TRIGGER IF EXISTS {MP}_guard ON {MP}")
    op.execute("DROP FUNCTION IF EXISTS pagos_mercadopago_guard()")
    op.execute(GUARD_FN_ANTERIOR)
    op.drop_constraint(
        op.f("ck_pagos_comprobantes_archivo_segun_origen"), "pagos_comprobantes", type_="check"
    )
    op.drop_constraint(op.f("ck_pagos_comprobantes_origen_valido"), "pagos_comprobantes", type_="check")
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('pagos_comprobantes', 'sha256',
               existing_type=sa.VARCHAR(length=64),
               nullable=False)
    op.alter_column('pagos_comprobantes', 'tamano_bytes',
               existing_type=sa.BIGINT(),
               nullable=False)
    op.alter_column('pagos_comprobantes', 'mime_type',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
    op.alter_column('pagos_comprobantes', 'archivo',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)
    op.alter_column('pagos_comprobantes', 'nombre_original',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)
    op.drop_column('pagos_comprobantes', 'origen')
    op.drop_index(op.f('ix_pagos_mercadopago_boleta_id'), table_name='pagos_mercadopago')
    op.drop_table('pagos_mercadopago')
    # ### end Alembic commands ###
