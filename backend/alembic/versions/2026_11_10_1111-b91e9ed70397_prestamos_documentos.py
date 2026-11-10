"""prestamos_documentos: documentación de las solicitudes de préstamo

Anexo I: carga de la documentación requerida. Los archivos se validan como los comprobantes
(regla MIME). La base garantiza que solo se agregan o anulan mientras la solicitud está abierta
y que nunca se borran ni se modifican (regla INM): anular es la única actualización.

Revision ID: b91e9ed70397
Revises: e7c2a9b41f58
Create Date: 2026-11-10 11:11:05.162302

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b91e9ed70397"
down_revision: str | None = "e7c2a9b41f58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "prestamos_documentos"

GUARD_FN = """
CREATE OR REPLACE FUNCTION prestamos_documentos_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    prestamo_estado text;
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION '%: % no permitido (sin borrado físico, regla INM)', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        -- Lo único que cambia es la anulación, una sola vez.
        IF OLD.anulado_en IS NOT NULL OR NEW.anulado_en IS NULL
           OR (NEW.id, NEW.prestamo_id, NEW.tipo, NEW.descripcion, NEW.nombre_original,
               NEW.archivo, NEW.mime_type, NEW.tamano_bytes, NEW.sha256,
               NEW.subido_por_user_id, NEW.created_at)
              IS DISTINCT FROM
              (OLD.id, OLD.prestamo_id, OLD.tipo, OLD.descripcion, OLD.nombre_original,
               OLD.archivo, OLD.mime_type, OLD.tamano_bytes, OLD.sha256,
               OLD.subido_por_user_id, OLD.created_at) THEN
            RAISE EXCEPTION 'prestamos_documentos: un documento no se modifica (solo se anula)'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    SELECT estado INTO prestamo_estado FROM prestamos WHERE id = NEW.prestamo_id;
    IF prestamo_estado IS DISTINCT FROM 'SOLICITADO' THEN
        RAISE EXCEPTION 'prestamos_documentos: la documentación de un préstamo resuelto no cambia'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;
"""


def upgrade() -> None:
    op.create_table(
        "prestamos_documentos",
        sa.Column("prestamo_id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("descripcion", sa.String(length=200), nullable=True),
        sa.Column("nombre_original", sa.String(length=255), nullable=False),
        sa.Column("archivo", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=50), nullable=False),
        sa.Column("tamano_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("subido_por_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("anulado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anulado_por_user_id", sa.UUID(), nullable=True),
        sa.Column("motivo_anulacion", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "mime_type IN ('application/pdf', 'image/png', 'image/jpeg')",
            name=op.f("ck_prestamos_documentos_mime"),
        ),
        sa.CheckConstraint(
            "tipo <> 'OTRO' OR descripcion IS NOT NULL",
            name=op.f("ck_prestamos_documentos_otro_descripto"),
        ),
        sa.CheckConstraint(
            "tipo IN ('DOCUMENTO_IDENTIDAD', 'CERTIFICADO_INGRESOS', 'CERTIFICADO_BIENES', 'GARANTIA', 'OTRO')",
            name=op.f("ck_prestamos_documentos_tipo_valido"),
        ),
        sa.CheckConstraint(
            "(anulado_en IS NULL) = (anulado_por_user_id IS NULL) AND (anulado_en IS NULL) = (motivo_anulacion IS NULL)",
            name=op.f("ck_prestamos_documentos_anulacion_completa"),
        ),
        sa.CheckConstraint("tamano_bytes > 0", name=op.f("ck_prestamos_documentos_tamano")),
        sa.ForeignKeyConstraint(
            ["anulado_por_user_id"],
            ["security_users.id"],
            name=op.f("fk_prestamos_documentos_anulado_por_user_id_security_users"),
        ),
        sa.ForeignKeyConstraint(
            ["prestamo_id"],
            ["prestamos.id"],
            name=op.f("fk_prestamos_documentos_prestamo_id_prestamos"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subido_por_user_id"],
            ["security_users.id"],
            name=op.f("fk_prestamos_documentos_subido_por_user_id_security_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prestamos_documentos")),
    )
    op.create_index(
        "ix_prestamos_documentos_prestamo_tipo",
        "prestamos_documentos",
        ["prestamo_id", "tipo"],
        unique=False,
    )
    op.execute(GUARD_FN)
    # Como el resto de préstamos: la aplicación no borra ni vacía (además del trigger).
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
        "FOR EACH ROW EXECUTE FUNCTION prestamos_documentos_guard()"
    )
    op.execute(
        f"CREATE TRIGGER {TABLA}_no_truncate BEFORE TRUNCATE ON {TABLA} "
        "FOR EACH STATEMENT EXECUTE FUNCTION prestamos_documentos_guard()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {TABLA}_no_truncate ON {TABLA}")
    op.execute(f"DROP TRIGGER IF EXISTS {TABLA}_guard ON {TABLA}")
    op.drop_index("ix_prestamos_documentos_prestamo_tipo", table_name=TABLA)
    op.drop_table(TABLA)
    op.execute("DROP FUNCTION IF EXISTS prestamos_documentos_guard()")
