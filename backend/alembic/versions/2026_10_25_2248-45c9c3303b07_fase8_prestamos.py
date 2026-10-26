"""fase8_prestamos

Revision ID: 45c9c3303b07
Revises: d6c44b1f2cff
Create Date: 2026-10-25 22:48:04.270624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

TABLES = ("prestamos_lineas", "prestamos", "prestamos_cuotas")

# Permisos nuevos del módulo (deben coincidir con app/modules/iam/catalog.py; lo verifica
# tests/iam/test_catalog.py) y los roles que los reciben.
PERMISOS = [
    ("prestamos:read_own", "Simular préstamos y consultar los propios"),
    ("prestamos:read_all", "Consultar préstamos de cualquier escribano"),
    ("prestamos:manage", "Administrar líneas de crédito y cargar solicitudes de préstamo"),
    ("prestamos:approve", "Otorgar o rechazar solicitudes de préstamo cargadas por otra persona"),
    ("prestamos:cobrar", "Registrar el pago de cuotas de préstamos"),
]
ROLES_PERMISOS = [
    ("ROLE_ESCRIBANO", "prestamos:read_own"),
    ("ROLE_ADMIN", "prestamos:read_all"),
    ("ROLE_ADMIN", "prestamos:manage"),
    ("ROLE_ADMIN", "prestamos:approve"),
    ("ROLE_ADMIN", "prestamos:cobrar"),
    ("ROLE_CAJA", "prestamos:read_all"),
    ("ROLE_CAJA", "prestamos:manage"),
    ("ROLE_TESORERIA", "prestamos:read_all"),
    ("ROLE_TESORERIA", "prestamos:cobrar"),
    ("ROLE_AUDITOR", "prestamos:read_all"),
]

GUARD_FN = """
CREATE OR REPLACE FUNCTION prestamos_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    prestamo_estado text;
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION '%: % no permitido (sin borrado físico, regla INM)', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- plpgsql no corta la evaluación de AND: cada tabla en su propio IF.
    IF TG_TABLE_NAME = 'prestamos' THEN
        IF OLD.estado <> 'SOLICITADO' THEN
            -- Resuelto: solo un otorgado pasa a cancelado, sin tocar nada más.
            IF NOT (OLD.estado = 'OTORGADO' AND NEW.estado = 'CANCELADO'
                    AND (NEW.id, NEW.numero, NEW.escribano_id, NEW.linea_id,
                         NEW.garante_escribano_id, NEW.sistema, NEW.tna, NEW.capital,
                         NEW.cuotas, NEW.ingreso_neto, NEW.otras_cuotas, NEW.cuota_maxima,
                         NEW.afectacion, NEW.afectacion_maxima, NEW.fecha_otorgamiento,
                         NEW.creado_por_user_id, NEW.resuelto_por_user_id, NEW.resuelto_en)
                        IS NOT DISTINCT FROM
                        (OLD.id, OLD.numero, OLD.escribano_id, OLD.linea_id,
                         OLD.garante_escribano_id, OLD.sistema, OLD.tna, OLD.capital,
                         OLD.cuotas, OLD.ingreso_neto, OLD.otras_cuotas, OLD.cuota_maxima,
                         OLD.afectacion, OLD.afectacion_maxima, OLD.fecha_otorgamiento,
                         OLD.creado_por_user_id, OLD.resuelto_por_user_id, OLD.resuelto_en)) THEN
                RAISE EXCEPTION 'prestamos: un préstamo % no se modifica', OLD.estado
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
        ELSIF NEW.estado NOT IN ('SOLICITADO', 'OTORGADO', 'RECHAZADO') THEN
            RAISE EXCEPTION 'prestamos: una solicitud no pasa directo a %', NEW.estado
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'prestamos_cuotas' THEN
        IF TG_OP = 'INSERT' THEN
            -- El plan se genera una sola vez, al otorgar (mientras la solicitud está abierta).
            SELECT estado INTO prestamo_estado FROM prestamos WHERE id = NEW.prestamo_id;
            IF prestamo_estado IS DISTINCT FROM 'SOLICITADO' THEN
                RAISE EXCEPTION 'prestamos_cuotas: el plan de un préstamo resuelto no cambia'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
        ELSIF OLD.estado <> 'PENDIENTE'
           OR (NEW.id, NEW.prestamo_id, NEW.numero, NEW.vencimiento, NEW.saldo_inicial,
               NEW.amortizacion, NEW.interes, NEW.cuota, NEW.saldo_final)
              IS DISTINCT FROM
              (OLD.id, OLD.prestamo_id, OLD.numero, OLD.vencimiento, OLD.saldo_inicial,
               OLD.amortizacion, OLD.interes, OLD.cuota, OLD.saldo_final) THEN
            RAISE EXCEPTION 'prestamos_cuotas: una cuota solo cambia al registrar su pago'
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
revision: str = '45c9c3303b07'
down_revision: Union[str, Sequence[str], None] = 'd6c44b1f2cff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SEQUENCE prestamos_numero_seq START 1")
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('prestamos_lineas',
    sa.Column('codigo', sa.String(length=50), nullable=False),
    sa.Column('nombre', sa.String(length=150), nullable=False),
    sa.Column('descripcion', sa.Text(), nullable=True),
    sa.Column('sistema', sa.String(length=10), nullable=False),
    sa.Column('plazo_minimo', sa.Integer(), nullable=False),
    sa.Column('plazo_maximo', sa.Integer(), nullable=False),
    sa.Column('monto_minimo', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('monto_maximo', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('tna', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('afectacion_maxima', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('requiere_garante', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('es_ejemplo', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("codigo ~ '^[A-Z][A-Z0-9_]{2,49}$'", name=op.f('ck_prestamos_lineas_codigo_formato')),
    sa.CheckConstraint("sistema IN ('FRANCES', 'ALEMAN')", name=op.f('ck_prestamos_lineas_sistema')),
    sa.CheckConstraint('afectacion_maxima > 0 AND afectacion_maxima <= 100', name=op.f('ck_prestamos_lineas_afectacion')),
    sa.CheckConstraint('monto_minimo > 0 AND monto_maximo >= monto_minimo', name=op.f('ck_prestamos_lineas_montos')),
    sa.CheckConstraint('plazo_maximo <= 360', name=op.f('ck_prestamos_lineas_plazo_tope')),
    sa.CheckConstraint('plazo_minimo > 0 AND plazo_maximo >= plazo_minimo', name=op.f('ck_prestamos_lineas_plazos')),
    sa.CheckConstraint('tna >= 0 AND tna <= 1000', name=op.f('ck_prestamos_lineas_tna')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['security_users.id'], name=op.f('fk_prestamos_lineas_created_by_user_id_security_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prestamos_lineas')),
    sa.UniqueConstraint('codigo', name=op.f('uq_prestamos_lineas_codigo'))
    )
    op.create_table('prestamos',
    sa.Column('numero', sa.Integer(), server_default=sa.text("nextval('prestamos_numero_seq')"), nullable=False),
    sa.Column('escribano_id', sa.UUID(), nullable=False),
    sa.Column('linea_id', sa.UUID(), nullable=False),
    sa.Column('garante_escribano_id', sa.UUID(), nullable=True),
    sa.Column('estado', sa.String(length=20), server_default='SOLICITADO', nullable=False),
    sa.Column('sistema', sa.String(length=10), nullable=False),
    sa.Column('tna', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('capital', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('cuotas', sa.Integer(), nullable=False),
    sa.Column('tasa_es_ejemplo', sa.Boolean(), nullable=False),
    sa.Column('ingreso_neto', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('otras_cuotas', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('cuota_maxima', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('afectacion', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('afectacion_maxima', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('observaciones', sa.Text(), nullable=True),
    sa.Column('motivo_rechazo', sa.Text(), nullable=True),
    sa.Column('fecha_otorgamiento', sa.Date(), nullable=True),
    sa.Column('creado_por_user_id', sa.UUID(), nullable=False),
    sa.Column('resuelto_por_user_id', sa.UUID(), nullable=True),
    sa.Column('resuelto_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(estado = 'RECHAZADO') = (motivo_rechazo IS NOT NULL)", name=op.f('ck_prestamos_rechazo_fundado')),
    sa.CheckConstraint("(estado IN ('OTORGADO', 'CANCELADO')) = (fecha_otorgamiento IS NOT NULL)", name=op.f('ck_prestamos_otorgamiento_coherente')),
    sa.CheckConstraint("estado IN ('SOLICITADO', 'OTORGADO', 'RECHAZADO', 'CANCELADO')", name=op.f('ck_prestamos_estado_valido')),
    sa.CheckConstraint("sistema IN ('FRANCES', 'ALEMAN')", name=op.f('ck_prestamos_sistema')),
    sa.CheckConstraint('afectacion <= afectacion_maxima', name=op.f('ck_prestamos_dentro_del_tope')),
    sa.CheckConstraint('capital > 0', name=op.f('ck_prestamos_capital')),
    sa.CheckConstraint('cuotas > 0', name=op.f('ck_prestamos_cuotas')),
    sa.CheckConstraint('garante_escribano_id IS DISTINCT FROM escribano_id', name=op.f('ck_prestamos_garante_propio')),
    sa.CheckConstraint('ingreso_neto > 0', name=op.f('ck_prestamos_ingreso')),
    sa.CheckConstraint('resuelto_por_user_id IS NULL OR resuelto_por_user_id <> creado_por_user_id', name=op.f('ck_prestamos_cuatro_ojos')),
    sa.ForeignKeyConstraint(['creado_por_user_id'], ['security_users.id'], name=op.f('fk_prestamos_creado_por_user_id_security_users')),
    sa.ForeignKeyConstraint(['escribano_id'], ['padron_escribanos.id'], name=op.f('fk_prestamos_escribano_id_padron_escribanos'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['garante_escribano_id'], ['padron_escribanos.id'], name=op.f('fk_prestamos_garante_escribano_id_padron_escribanos'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['linea_id'], ['prestamos_lineas.id'], name=op.f('fk_prestamos_linea_id_prestamos_lineas'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['resuelto_por_user_id'], ['security_users.id'], name=op.f('fk_prestamos_resuelto_por_user_id_security_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prestamos')),
    sa.UniqueConstraint('numero', name=op.f('uq_prestamos_numero'))
    )
    op.create_index('ix_prestamos_escribano_estado', 'prestamos', ['escribano_id', 'estado'], unique=False)
    op.create_index(op.f('ix_prestamos_estado'), 'prestamos', ['estado'], unique=False)
    op.create_index(op.f('ix_prestamos_garante_escribano_id'), 'prestamos', ['garante_escribano_id'], unique=False)
    op.create_table('prestamos_cuotas',
    sa.Column('prestamo_id', sa.UUID(), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('vencimiento', sa.Date(), nullable=False),
    sa.Column('saldo_inicial', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('amortizacion', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('interes', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('cuota', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('saldo_final', sa.Numeric(precision=15, scale=2), nullable=False),
    sa.Column('estado', sa.String(length=20), server_default='PENDIENTE', nullable=False),
    sa.Column('fecha_pago', sa.Date(), nullable=True),
    sa.Column('importe_pagado', sa.Numeric(precision=15, scale=2), nullable=True),
    sa.Column('registrado_por_user_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.CheckConstraint("(estado = 'PAGADA') = (fecha_pago IS NOT NULL AND importe_pagado IS NOT NULL AND registrado_por_user_id IS NOT NULL)", name=op.f('ck_prestamos_cuotas_pago_coherente')),
    sa.CheckConstraint("estado IN ('PENDIENTE', 'PAGADA')", name=op.f('ck_prestamos_cuotas_estado_valido')),
    sa.CheckConstraint('amortizacion > 0 AND interes >= 0 AND saldo_final >= 0', name=op.f('ck_prestamos_cuotas_valores')),
    sa.CheckConstraint('cuota = amortizacion + interes', name=op.f('ck_prestamos_cuotas_cuota_cuadra')),
    sa.CheckConstraint('numero > 0', name=op.f('ck_prestamos_cuotas_numero')),
    sa.CheckConstraint('saldo_final = saldo_inicial - amortizacion', name=op.f('ck_prestamos_cuotas_saldo_cuadra')),
    sa.ForeignKeyConstraint(['prestamo_id'], ['prestamos.id'], name=op.f('fk_prestamos_cuotas_prestamo_id_prestamos'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['registrado_por_user_id'], ['security_users.id'], name=op.f('fk_prestamos_cuotas_registrado_por_user_id_security_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prestamos_cuotas')),
    sa.UniqueConstraint('prestamo_id', 'numero', name='uq_prestamos_cuotas_numero')
    )
    op.create_index(op.f('ix_prestamos_cuotas_prestamo_id'), 'prestamos_cuotas', ['prestamo_id'], unique=False)
    op.create_index('ix_prestamos_cuotas_vencimiento_estado', 'prestamos_cuotas', ['vencimiento', 'estado'], unique=False)
    # ### end Alembic commands ###
    op.execute(GUARD_FN)
    for table in TABLES:
        _revoke_from_app_roles(table, "DELETE, TRUNCATE")
        op.execute(
            f"CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION prestamos_guard()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION prestamos_guard()"
        )
    op.execute(
        "CREATE TRIGGER prestamos_cuotas_insert_guard BEFORE INSERT ON prestamos_cuotas "
        "FOR EACH ROW EXECUTE FUNCTION prestamos_guard()"
    )
    permisos = sa.table(
        "security_permissions",
        sa.column("code", sa.String()),
        sa.column("module", sa.String()),
        sa.column("description", sa.Text()),
    )
    op.bulk_insert(
        permisos, [{"code": c, "module": "prestamos", "description": d} for c, d in PERMISOS]
    )
    for rol, permiso in ROLES_PERMISOS:
        op.execute(
            sa.text(
                "INSERT INTO security_role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM security_roles r, security_permissions p "
                "WHERE r.code = :rol AND p.code = :permiso"
            ).bindparams(rol=rol, permiso=permiso)
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM security_role_permissions WHERE permission_id IN "
        "(SELECT id FROM security_permissions WHERE module = 'prestamos')"
    )
    op.execute("DELETE FROM security_permissions WHERE module = 'prestamos'")
    op.execute("DROP TRIGGER IF EXISTS prestamos_cuotas_insert_guard ON prestamos_cuotas")
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_guard ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_prestamos_cuotas_vencimiento_estado', table_name='prestamos_cuotas')
    op.drop_index(op.f('ix_prestamos_cuotas_prestamo_id'), table_name='prestamos_cuotas')
    op.drop_table('prestamos_cuotas')
    op.drop_index(op.f('ix_prestamos_garante_escribano_id'), table_name='prestamos')
    op.drop_index(op.f('ix_prestamos_estado'), table_name='prestamos')
    op.drop_index('ix_prestamos_escribano_estado', table_name='prestamos')
    op.drop_table('prestamos')
    op.drop_table('prestamos_lineas')
    # ### end Alembic commands ###
    op.execute("DROP FUNCTION IF EXISTS prestamos_guard()")
    op.execute("DROP SEQUENCE IF EXISTS prestamos_numero_seq")
