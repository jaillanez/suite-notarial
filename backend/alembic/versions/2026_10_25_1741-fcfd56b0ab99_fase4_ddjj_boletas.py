"""fase4_ddjj_boletas

Revision ID: fcfd56b0ab99
Revises: c93e7858de9f
Create Date: 2026-10-25 17:41:45.886826

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


TABLES = ("ddjj_vencimientos", "ddjj_declaraciones", "ddjj_actos", "ddjj_boletas")

GUARD_FN = """
CREATE OR REPLACE FUNCTION ddjj_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    ddjj_estado text;
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION '%: % no permitido (sin borrado físico, regla INM)', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- plpgsql no corta la evaluación de AND: cada tabla va en su propio IF porque OLD y NEW
    -- tienen la forma de la fila de esa tabla (y no existen según la operación).
    IF TG_TABLE_NAME = 'ddjj_actos' THEN
        -- Los actos solo se agregan o cambian mientras su DDJJ está en borrador. La única
        -- excepción es congelar la liquidación al presentar (aporte y vigencia de NULL a valor).
        SELECT estado INTO ddjj_estado FROM ddjj_declaraciones WHERE id = NEW.ddjj_id;
        IF TG_OP = 'UPDATE' THEN
            IF OLD.aporte IS NOT NULL OR NEW.ddjj_id IS DISTINCT FROM OLD.ddjj_id THEN
                RAISE EXCEPTION 'ddjj_actos: un acto liquidado no se modifica (usar rectificativa)'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
        END IF;
        IF ddjj_estado IS DISTINCT FROM 'BORRADOR' THEN
            RAISE EXCEPTION 'ddjj_actos: la DDJJ no está en borrador'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'ddjj_declaraciones' THEN
        -- Presentada: solo puede pasar a RECTIFICADA, sin tocar nada más.
        IF OLD.estado <> 'BORRADOR'
           AND NOT (OLD.estado = 'PRESENTADA' AND NEW.estado = 'RECTIFICADA'
                AND (NEW.id, NEW.registro_id, NEW.periodo, NEW.numero_rectificativa,
                     NEW.observaciones, NEW.fecha_presentacion, NEW.presentada_por_user_id,
                     NEW.rectifica_a_id, NEW.created_by_user_id, NEW.created_at,
                     NEW.total_protocolos, NEW.cantidad_actos)
                    IS NOT DISTINCT FROM
                    (OLD.id, OLD.registro_id, OLD.periodo, OLD.numero_rectificativa,
                     OLD.observaciones, OLD.fecha_presentacion, OLD.presentada_por_user_id,
                     OLD.rectifica_a_id, OLD.created_by_user_id, OLD.created_at,
                     OLD.total_protocolos, OLD.cantidad_actos)) THEN
            RAISE EXCEPTION 'ddjj_declaraciones: una DDJJ % no se modifica', OLD.estado
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'ddjj_vencimientos' THEN
        -- El vencimiento se corrige solo mientras no haya boletas del período.
        IF NEW.periodo IS DISTINCT FROM OLD.periodo
           OR (NEW.fecha_vencimiento IS DISTINCT FROM OLD.fecha_vencimiento
               AND EXISTS (SELECT 1 FROM ddjj_boletas WHERE periodo = OLD.periodo)) THEN
            RAISE EXCEPTION 'ddjj_vencimientos: el período % ya tiene boletas emitidas', OLD.periodo
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'ddjj_boletas' THEN
        -- Solo cambia el estado (PENDIENTE -> PAGADA o ANULADA) y los datos de anulación.
        IF OLD.estado <> 'PENDIENTE'
           OR (NEW.id, NEW.numero, NEW.codigo_verificacion, NEW.ddjj_id, NEW.registro_id,
               NEW.periodo, NEW.fecha_emision, NEW.fecha_vencimiento, NEW.fecha_pago,
               NEW.dias_mora, NEW.total_protocolos, NEW.aporte_minimo, NEW.excedente,
               NEW.aporte_medico, NEW.cantidad_aportes_medicos, NEW.total_en_termino,
               NEW.interes_mora, NEW.total_a_pagar, NEW.vigencia_minimo_id,
               NEW.vigencia_medico_id, NEW.vigencia_mora_id, NEW.checksum_sha256,
               NEW.emitida_por_user_id, NEW.created_at)
              IS DISTINCT FROM
              (OLD.id, OLD.numero, OLD.codigo_verificacion, OLD.ddjj_id, OLD.registro_id,
               OLD.periodo, OLD.fecha_emision, OLD.fecha_vencimiento, OLD.fecha_pago,
               OLD.dias_mora, OLD.total_protocolos, OLD.aporte_minimo, OLD.excedente,
               OLD.aporte_medico, OLD.cantidad_aportes_medicos, OLD.total_en_termino,
               OLD.interes_mora, OLD.total_a_pagar, OLD.vigencia_minimo_id,
               OLD.vigencia_medico_id, OLD.vigencia_mora_id, OLD.checksum_sha256,
               OLD.emitida_por_user_id, OLD.created_at) THEN
            RAISE EXCEPTION 'ddjj_boletas: una boleta emitida no se modifica'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
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

# revision identifiers, used by Alembic.
revision: str = 'fcfd56b0ab99'
down_revision: Union[str, Sequence[str], None] = 'c93e7858de9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Numeración correlativa y única aun con emisiones concurrentes (secuencia de la base).
    # Una transacción revertida puede dejar un número sin usar (ninguna boleta lo lleva).
    op.execute("CREATE SEQUENCE ddjj_boletas_numero_seq START 1")
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('ddjj_vencimientos',
    sa.Column('periodo', sa.String(length=7), nullable=False),
    sa.Column('fecha_vencimiento', sa.Date(), nullable=False),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("periodo ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name=op.f('ck_ddjj_vencimientos_periodo_formato')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['security_users.id'], name=op.f('fk_ddjj_vencimientos_created_by_user_id_security_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ddjj_vencimientos')),
    sa.UniqueConstraint('periodo', name=op.f('uq_ddjj_vencimientos_periodo'))
    )
    op.create_table('ddjj_declaraciones',
    sa.Column('registro_id', sa.UUID(), nullable=False),
    sa.Column('periodo', sa.String(length=7), nullable=False),
    sa.Column('numero_rectificativa', sa.Integer(), server_default='0', nullable=False),
    sa.Column('estado', sa.String(length=20), server_default='BORRADOR', nullable=False),
    sa.Column('observaciones', sa.Text(), nullable=True),
    sa.Column('fecha_presentacion', sa.DateTime(timezone=True), nullable=True),
    sa.Column('presentada_por_user_id', sa.UUID(), nullable=True),
    sa.Column('rectifica_a_id', sa.UUID(), nullable=True),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('total_protocolos', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('cantidad_actos', sa.Integer(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("estado IN ('BORRADOR', 'PRESENTADA', 'RECTIFICADA')", name=op.f('ck_ddjj_declaraciones_estado_valido')),
    sa.CheckConstraint("periodo ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name=op.f('ck_ddjj_declaraciones_periodo_formato')),
    sa.CheckConstraint('numero_rectificativa >= 0', name=op.f('ck_ddjj_declaraciones_rectificativa')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['security_users.id'], name=op.f('fk_ddjj_declaraciones_created_by_user_id_security_users')),
    sa.ForeignKeyConstraint(['presentada_por_user_id'], ['security_users.id'], name=op.f('fk_ddjj_declaraciones_presentada_por_user_id_security_users')),
    sa.ForeignKeyConstraint(['rectifica_a_id'], ['ddjj_declaraciones.id'], name=op.f('fk_ddjj_declaraciones_rectifica_a_id_ddjj_declaraciones'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['registro_id'], ['padron_registros_notariales.id'], name=op.f('fk_ddjj_declaraciones_registro_id_padron_registros_notariales'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ddjj_declaraciones'))
    )
    op.create_index(op.f('ix_ddjj_declaraciones_estado'), 'ddjj_declaraciones', ['estado'], unique=False)
    op.create_index(op.f('ix_ddjj_declaraciones_periodo'), 'ddjj_declaraciones', ['periodo'], unique=False)
    op.create_index(op.f('ix_ddjj_declaraciones_registro_id'), 'ddjj_declaraciones', ['registro_id'], unique=False)
    op.create_index('uq_ddjj_declaraciones_registro_periodo_rect', 'ddjj_declaraciones', ['registro_id', 'periodo', 'numero_rectificativa'], unique=True)
    op.create_index('uq_ddjj_declaraciones_registro_periodo_vigente', 'ddjj_declaraciones', ['registro_id', 'periodo'], unique=True, postgresql_where=sa.text("estado <> 'RECTIFICADA'"))
    op.create_table('ddjj_actos',
    sa.Column('ddjj_id', sa.UUID(), nullable=False),
    sa.Column('escribano_id', sa.UUID(), nullable=False),
    sa.Column('cargo', sa.String(length=30), nullable=False),
    sa.Column('tipo_protocolo', sa.String(length=10), nullable=False),
    sa.Column('numero_escritura', sa.Integer(), nullable=False),
    sa.Column('folio', sa.Integer(), nullable=True),
    sa.Column('fecha_acto', sa.Date(), nullable=False),
    sa.Column('naturaleza', sa.String(length=300), nullable=False),
    sa.Column('categoria', sa.String(length=30), nullable=False),
    sa.Column('base_imponible', sa.Numeric(precision=18, scale=2), server_default='0', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('aporte', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('vigencia_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(categoria = 'ESCRITURA_CON_VALOR') = (base_imponible > 0)", name=op.f('ck_ddjj_actos_base_segun_categoria')),
    sa.CheckConstraint("categoria IN ('ESCRITURA_CON_VALOR', 'ACTA_O_PODER', 'OTRO_ACTO', 'SIN_EFECTO')", name=op.f('ck_ddjj_actos_categoria_valida')),
    sa.CheckConstraint("tipo_protocolo IN ('GENERAL', 'AUXILIAR')", name=op.f('ck_ddjj_actos_protocolo')),
    sa.CheckConstraint('base_imponible >= 0', name=op.f('ck_ddjj_actos_base')),
    sa.CheckConstraint('folio IS NULL OR folio > 0', name=op.f('ck_ddjj_actos_folio')),
    sa.CheckConstraint('numero_escritura > 0', name=op.f('ck_ddjj_actos_numero')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['security_users.id'], name=op.f('fk_ddjj_actos_created_by_user_id_security_users')),
    sa.ForeignKeyConstraint(['ddjj_id'], ['ddjj_declaraciones.id'], name=op.f('fk_ddjj_actos_ddjj_id_ddjj_declaraciones'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['escribano_id'], ['padron_escribanos.id'], name=op.f('fk_ddjj_actos_escribano_id_padron_escribanos'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['vigencia_id'], ['parametros_vigencias.id'], name=op.f('fk_ddjj_actos_vigencia_id_parametros_vigencias'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ddjj_actos'))
    )
    op.create_index(op.f('ix_ddjj_actos_ddjj_id'), 'ddjj_actos', ['ddjj_id'], unique=False)
    op.create_index('uq_ddjj_actos_escritura', 'ddjj_actos', ['ddjj_id', 'tipo_protocolo', 'numero_escritura'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('ddjj_boletas',
    sa.Column('numero', sa.Integer(), server_default=sa.text("nextval('ddjj_boletas_numero_seq')"), nullable=False),
    sa.Column('codigo_verificacion', sa.String(length=32), nullable=False),
    sa.Column('ddjj_id', sa.UUID(), nullable=False),
    sa.Column('registro_id', sa.UUID(), nullable=False),
    sa.Column('periodo', sa.String(length=7), nullable=False),
    sa.Column('estado', sa.String(length=20), server_default='PENDIENTE', nullable=False),
    sa.Column('fecha_emision', sa.Date(), nullable=False),
    sa.Column('fecha_vencimiento', sa.Date(), nullable=False),
    sa.Column('fecha_pago', sa.Date(), nullable=False),
    sa.Column('dias_mora', sa.Integer(), server_default='0', nullable=False),
    sa.Column('total_protocolos', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('aporte_minimo', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('excedente', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('aporte_medico', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('cantidad_aportes_medicos', sa.Integer(), nullable=False),
    sa.Column('total_en_termino', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('interes_mora', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('total_a_pagar', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('vigencia_minimo_id', sa.UUID(), nullable=False),
    sa.Column('vigencia_medico_id', sa.UUID(), nullable=False),
    sa.Column('vigencia_mora_id', sa.UUID(), nullable=True),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=False),
    sa.Column('emitida_por_user_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('anulada_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('motivo_anulacion', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.CheckConstraint("estado IN ('PENDIENTE', 'PAGADA', 'ANULADA')", name=op.f('ck_ddjj_boletas_estado_valido')),
    sa.CheckConstraint("periodo ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name=op.f('ck_ddjj_boletas_periodo_formato')),
    sa.CheckConstraint('fecha_pago >= fecha_emision', name=op.f('ck_ddjj_boletas_fecha_pago')),
    sa.CheckConstraint('dias_mora = 0 OR fecha_pago > fecha_vencimiento', name=op.f('ck_ddjj_boletas_mora_solo_fuera_de_termino')),
    sa.CheckConstraint('interes_mora = 0 OR dias_mora > 0', name=op.f('ck_ddjj_boletas_interes_con_mora')),
    sa.CheckConstraint('total_a_pagar = total_en_termino + interes_mora', name=op.f('ck_ddjj_boletas_total_cuadra')),
    sa.CheckConstraint('total_en_termino = aporte_minimo + excedente + aporte_medico', name=op.f('ck_ddjj_boletas_termino_cuadra')),
    sa.ForeignKeyConstraint(['ddjj_id'], ['ddjj_declaraciones.id'], name=op.f('fk_ddjj_boletas_ddjj_id_ddjj_declaraciones'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['emitida_por_user_id'], ['security_users.id'], name=op.f('fk_ddjj_boletas_emitida_por_user_id_security_users')),
    sa.ForeignKeyConstraint(['registro_id'], ['padron_registros_notariales.id'], name=op.f('fk_ddjj_boletas_registro_id_padron_registros_notariales'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['vigencia_medico_id'], ['parametros_vigencias.id'], name=op.f('fk_ddjj_boletas_vigencia_medico_id_parametros_vigencias'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['vigencia_minimo_id'], ['parametros_vigencias.id'], name=op.f('fk_ddjj_boletas_vigencia_minimo_id_parametros_vigencias'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['vigencia_mora_id'], ['parametros_vigencias.id'], name=op.f('fk_ddjj_boletas_vigencia_mora_id_parametros_vigencias'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ddjj_boletas')),
    sa.UniqueConstraint('codigo_verificacion', name=op.f('uq_ddjj_boletas_codigo_verificacion')),
    sa.UniqueConstraint('numero', name=op.f('uq_ddjj_boletas_numero'))
    )
    op.create_index(op.f('ix_ddjj_boletas_ddjj_id'), 'ddjj_boletas', ['ddjj_id'], unique=False)
    op.create_index(op.f('ix_ddjj_boletas_estado'), 'ddjj_boletas', ['estado'], unique=False)
    op.create_index(op.f('ix_ddjj_boletas_registro_id'), 'ddjj_boletas', ['registro_id'], unique=False)
    op.create_index('uq_ddjj_boletas_pendiente', 'ddjj_boletas', ['ddjj_id'], unique=True, postgresql_where=sa.text("estado = 'PENDIENTE'"))
    # ### end Alembic commands ###

    op.execute(GUARD_FN)
    for table in TABLES:
        _revoke_from_app_roles(table, "DELETE, TRUNCATE")
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION ddjj_guard()"
        )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION ddjj_guard()"
        )
    op.execute(
        "CREATE TRIGGER ddjj_actos_insert_guard BEFORE INSERT ON ddjj_actos "
        "FOR EACH ROW EXECUTE FUNCTION ddjj_guard()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS ddjj_actos_insert_guard ON ddjj_actos")
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_guard ON {table}")
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('uq_ddjj_boletas_pendiente', table_name='ddjj_boletas', postgresql_where=sa.text("estado = 'PENDIENTE'"))
    op.drop_index(op.f('ix_ddjj_boletas_registro_id'), table_name='ddjj_boletas')
    op.drop_index(op.f('ix_ddjj_boletas_estado'), table_name='ddjj_boletas')
    op.drop_index(op.f('ix_ddjj_boletas_ddjj_id'), table_name='ddjj_boletas')
    op.drop_table('ddjj_boletas')
    op.drop_index('uq_ddjj_actos_escritura', table_name='ddjj_actos', postgresql_where=sa.text('is_active'))
    op.drop_index(op.f('ix_ddjj_actos_ddjj_id'), table_name='ddjj_actos')
    op.drop_table('ddjj_actos')
    op.drop_index('uq_ddjj_declaraciones_registro_periodo_vigente', table_name='ddjj_declaraciones', postgresql_where=sa.text("estado <> 'RECTIFICADA'"))
    op.drop_index('uq_ddjj_declaraciones_registro_periodo_rect', table_name='ddjj_declaraciones')
    op.drop_index(op.f('ix_ddjj_declaraciones_registro_id'), table_name='ddjj_declaraciones')
    op.drop_index(op.f('ix_ddjj_declaraciones_periodo'), table_name='ddjj_declaraciones')
    op.drop_index(op.f('ix_ddjj_declaraciones_estado'), table_name='ddjj_declaraciones')
    op.drop_table('ddjj_declaraciones')
    op.drop_table('ddjj_vencimientos')
    # ### end Alembic commands ###
    op.execute("DROP FUNCTION IF EXISTS ddjj_guard()")
    op.execute("DROP SEQUENCE IF EXISTS ddjj_boletas_numero_seq")
