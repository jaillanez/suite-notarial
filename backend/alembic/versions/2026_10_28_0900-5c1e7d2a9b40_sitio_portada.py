"""sitio_portada: secciones e imagen de las notas, páginas institucionales y portada

Revision ID: 5c1e7d2a9b40
Revises: 1093a02ce864
Create Date: 2026-10-28 09:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5c1e7d2a9b40"
down_revision: Union[str, Sequence[str], None] = "1093a02ce864"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Igual que la de fase7_cms, más: páginas (sin borrado, lo publicado no vuelve a borrador ni
# cambia de enlace) y versiones de portada (inmutables: cada guardado es una fila nueva).
GUARD_FN = """
CREATE OR REPLACE FUNCTION cms_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION '%: % no permitido (sin borrado físico, regla INM)', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- plpgsql no corta la evaluación de AND: cada tabla en su propio IF.
    IF TG_TABLE_NAME IN ('cms_documento_versiones', 'cms_portada_versiones') THEN
        RAISE EXCEPTION '%: una versión guardada no se modifica', TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_TABLE_NAME = 'cms_documentos' THEN
        -- La URL canónica es permanente.
        IF NEW.slug IS DISTINCT FROM OLD.slug
           OR (OLD.primera_version_publica IS NOT NULL
               AND NEW.primera_version_publica IS DISTINCT FROM OLD.primera_version_publica) THEN
            RAISE EXCEPTION 'cms_documentos: el enlace permanente no cambia'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF TG_TABLE_NAME IN ('cms_novedades', 'cms_documentos') THEN
        -- Lo que se publicó una vez no vuelve a borrador (ni pierde su fecha de publicación).
        IF (OLD.estado <> 'BORRADOR' AND NEW.estado = 'BORRADOR')
           OR (OLD.fecha_publicacion IS NOT NULL
               AND NEW.fecha_publicacion IS DISTINCT FROM OLD.fecha_publicacion) THEN
            RAISE EXCEPTION '%: lo publicado no vuelve a borrador', TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'cms_paginas' THEN
        IF OLD.estado <> 'BORRADOR' AND NEW.estado = 'BORRADOR' THEN
            RAISE EXCEPTION 'cms_paginas: lo publicado no vuelve a borrador'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF TG_TABLE_NAME IN ('cms_novedades', 'cms_paginas') THEN
        IF NEW.slug IS DISTINCT FROM OLD.slug AND OLD.estado <> 'BORRADOR' THEN
            RAISE EXCEPTION '%: el enlace de lo publicado no cambia', TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'cms_novedades' THEN
        IF NEW.slug IS DISTINCT FROM OLD.slug AND OLD.fecha_publicacion IS NOT NULL THEN
            RAISE EXCEPTION 'cms_novedades: el enlace de una novedad publicada no cambia'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

GUARD_FN_ANTERIOR = """
CREATE OR REPLACE FUNCTION cms_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION '%: % no permitido (sin borrado físico, regla INM)', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- plpgsql no corta la evaluación de AND: cada tabla en su propio IF.
    IF TG_TABLE_NAME = 'cms_documento_versiones' THEN
        RAISE EXCEPTION 'cms_documento_versiones: una versión publicada no se modifica'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_TABLE_NAME = 'cms_documentos' THEN
        -- La URL canónica es permanente.
        IF NEW.slug IS DISTINCT FROM OLD.slug
           OR (OLD.primera_version_publica IS NOT NULL
               AND NEW.primera_version_publica IS DISTINCT FROM OLD.primera_version_publica) THEN
            RAISE EXCEPTION 'cms_documentos: el enlace permanente no cambia'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF TG_TABLE_NAME IN ('cms_novedades', 'cms_documentos') THEN
        -- Lo que se publicó una vez no vuelve a borrador (ni pierde su fecha de publicación).
        IF (OLD.estado <> 'BORRADOR' AND NEW.estado = 'BORRADOR')
           OR (OLD.fecha_publicacion IS NOT NULL
               AND NEW.fecha_publicacion IS DISTINCT FROM OLD.fecha_publicacion) THEN
            RAISE EXCEPTION '%: lo publicado no vuelve a borrador', TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'cms_novedades' THEN
        IF NEW.slug IS DISTINCT FROM OLD.slug
           AND (OLD.estado <> 'BORRADOR' OR OLD.fecha_publicacion IS NOT NULL) THEN
            RAISE EXCEPTION 'cms_novedades: el enlace de una novedad publicada no cambia'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

NUEVAS = ("cms_paginas", "cms_portada_versiones")


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
    op.add_column(
        "cms_novedades",
        sa.Column("seccion", sa.String(length=20), server_default="NOVEDADES", nullable=False),
    )
    op.add_column("cms_novedades", sa.Column("imagen_ruta", sa.String(length=255), nullable=True))
    op.add_column("cms_novedades", sa.Column("imagen_mime", sa.String(length=50), nullable=True))
    op.add_column("cms_novedades", sa.Column("imagen_sha256", sa.String(length=64), nullable=True))
    op.add_column("cms_novedades", sa.Column("imagen_alt", sa.String(length=200), nullable=True))
    op.create_index(op.f("ix_cms_novedades_seccion"), "cms_novedades", ["seccion"], unique=False)
    op.create_check_constraint(
        op.f("ck_cms_novedades_seccion_valida"),
        "cms_novedades",
        "seccion IN ('NOVEDADES', 'COMUNICADOS', 'APORTES', 'INSTITUCIONAL')",
    )
    op.create_check_constraint(
        op.f("ck_cms_novedades_imagen_completa"),
        "cms_novedades",
        "(imagen_ruta IS NULL) = (imagen_sha256 IS NULL)"
        " AND (imagen_ruta IS NULL) = (imagen_mime IS NULL)",
    )

    op.create_table(
        "cms_paginas",
        sa.Column("slug", sa.String(length=150), nullable=False),
        sa.Column("grupo", sa.String(length=20), nullable=False),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("contenido", sa.Text(), nullable=False),
        sa.Column("orden", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estado", sa.String(length=20), server_default="BORRADOR", nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f("ck_cms_paginas_slug_formato")),
        sa.CheckConstraint(
            "estado IN ('BORRADOR', 'PUBLICADO', 'ARCHIVADO')", name=op.f("ck_cms_paginas_estado_valido")
        ),
        sa.CheckConstraint("grupo IN ('CAJA', 'NORMATIVA')", name=op.f("ck_cms_paginas_grupo_valido")),
        sa.CheckConstraint("orden >= 0", name=op.f("ck_cms_paginas_orden")),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["security_users.id"],
            name=op.f("fk_cms_paginas_created_by_user_id_security_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cms_paginas")),
        sa.UniqueConstraint("slug", name=op.f("uq_cms_paginas_slug")),
    )
    op.create_table(
        "cms_portada_versiones",
        sa.Column("configuracion", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("creado_por_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["creado_por_user_id"],
            ["security_users.id"],
            name=op.f("fk_cms_portada_versiones_creado_por_user_id_security_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cms_portada_versiones")),
    )
    op.create_index(
        op.f("ix_cms_portada_versiones_created_at"),
        "cms_portada_versiones",
        ["created_at"],
        unique=False,
    )

    op.execute(GUARD_FN)
    for table in NUEVAS:
        op.execute(
            f"CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION cms_guard()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION cms_guard()"
        )
        _revoke_from_app_roles(table, "DELETE, TRUNCATE")
    _revoke_from_app_roles("cms_portada_versiones", "UPDATE")


def downgrade() -> None:
    for table in NUEVAS:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_guard ON {table}")
    op.execute(GUARD_FN_ANTERIOR)
    op.drop_index(op.f("ix_cms_portada_versiones_created_at"), table_name="cms_portada_versiones")
    op.drop_table("cms_portada_versiones")
    op.drop_table("cms_paginas")
    op.drop_constraint(op.f("ck_cms_novedades_imagen_completa"), "cms_novedades", type_="check")
    op.drop_constraint(op.f("ck_cms_novedades_seccion_valida"), "cms_novedades", type_="check")
    op.drop_index(op.f("ix_cms_novedades_seccion"), table_name="cms_novedades")
    op.drop_column("cms_novedades", "imagen_alt")
    op.drop_column("cms_novedades", "imagen_sha256")
    op.drop_column("cms_novedades", "imagen_mime")
    op.drop_column("cms_novedades", "imagen_ruta")
    op.drop_column("cms_novedades", "seccion")
