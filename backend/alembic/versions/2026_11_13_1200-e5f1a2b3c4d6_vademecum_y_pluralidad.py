"""vademécum de aportes, criterio de pluralidad, precio y avalúo de cada acto

- `ddjj_vademecum`: actos del vademécum con su categoría y vigencia, aprobados por otra persona;
  inmutable salvo la aprobación y el cierre de la vigencia, sin borrado ni solapamiento.
- Motor paramétrico: tipo CRITERIO_PLURALIDAD con la columna `criterio`, inmutable como el resto
  de los valores de una vigencia.
- `ddjj_actos`: vademécum elegido (o «fuera de vademécum»), precio, avalúo, mismas partes de la
  escritura, aporte individual y vigencia del criterio congelados al presentar. Dos motivos de
  exención nuevos del vademécum.

Revision ID: e5f1a2b3c4d6
Revises: d4e9f0a1b2c3
Create Date: 2026-11-13 12:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e5f1a2b3c4d6"
down_revision: Union[str, Sequence[str], None] = "d4e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TIPOS_ANTES = "'PORCENTUAL_ACTO', 'FIJO_ACTO', 'FIJO_MENSUAL', 'TASA_MORA'"
TIPOS = TIPOS_ANTES + ", 'CRITERIO_PLURALIDAD'"
MOTIVOS_ANTES = "'CONVENIO_IPV', 'ACTA_SUBSANATORIA', 'OTRO'"
MOTIVOS = "'CONVENIO_IPV', 'ACTA_SUBSANATORIA', 'REGULACION_DOMINIAL', 'ASOCIACION_INTERMEDIA_IPV', 'OTRO'"


def _guard_vigencias(con_criterio: bool) -> str:
    criterio_new = " NEW.criterio," if con_criterio else ""
    criterio_old = " OLD.criterio," if con_criterio else ""
    return f"""
CREATE OR REPLACE FUNCTION parametros_vigencia_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION 'parametros_vigencias: % no permitido (una vigencia nunca se borra)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- Los valores, el concepto y el respaldo de una vigencia nunca cambian.
    IF (NEW.concepto_id, NEW.version, NEW.fecha_desde, NEW.porcentaje, NEW.monto_fijo,
        NEW.monto_minimo, NEW.monto_maximo, NEW.tasa, NEW.periodo_tasa, NEW.dias_gracia,{criterio_new}
        NEW.regla_redondeo, NEW.es_ejemplo, NEW.resolucion_respaldo, NEW.motivo,
        NEW.created_by_user_id, NEW.created_at)
       IS DISTINCT FROM
       (OLD.concepto_id, OLD.version, OLD.fecha_desde, OLD.porcentaje, OLD.monto_fijo,
        OLD.monto_minimo, OLD.monto_maximo, OLD.tasa, OLD.periodo_tasa, OLD.dias_gracia,{criterio_old}
        OLD.regla_redondeo, OLD.es_ejemplo, OLD.resolucion_respaldo, OLD.motivo,
        OLD.created_by_user_id, OLD.created_at) THEN
        RAISE EXCEPTION 'parametros_vigencias: los valores de una vigencia no se modifican'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- Solo se puede cerrar una vigencia abierta (fecha_hasta de NULL a una fecha).
    IF NEW.fecha_hasta IS DISTINCT FROM OLD.fecha_hasta AND OLD.fecha_hasta IS NOT NULL THEN
        RAISE EXCEPTION 'parametros_vigencias: una vigencia cerrada no se reabre ni se corre'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- Estados: solo PENDIENTE_APROBACION pasa a VIGENTE o RECHAZADA.
    IF NEW.estado IS DISTINCT FROM OLD.estado AND OLD.estado <> 'PENDIENTE_APROBACION' THEN
        RAISE EXCEPTION 'parametros_vigencias: el estado % es definitivo', OLD.estado
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;
"""


VADEMECUM_GUARD = """
CREATE OR REPLACE FUNCTION ddjj_vademecum_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION 'ddjj_vademecum: % no permitido (un acto del vademécum nunca se borra)',
            TG_OP USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- Una versión no cambia: solo se aprueba o rechaza una vez (cuatro ojos, lo controlan los
    -- CHECK) y se cierra su vigencia abierta (fecha_hasta de NULL a fecha).
    IF NEW.estado IS DISTINCT FROM OLD.estado AND OLD.estado <> 'PENDIENTE_APROBACION' THEN
        RAISE EXCEPTION 'ddjj_vademecum: el estado % es definitivo', OLD.estado
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.estado = OLD.estado AND (NEW.aprobado_por_user_id, NEW.fecha_aprobacion)
       IS DISTINCT FROM (OLD.aprobado_por_user_id, OLD.fecha_aprobacion) THEN
        RAISE EXCEPTION 'ddjj_vademecum: la aprobación no se modifica'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF (NEW.id, NEW.codigo, NEW.version, NEW.nombre, NEW.categoria, NEW.motivo_exencion,
        NEW.aclaracion, NEW.sinonimos, NEW.orden, NEW.fecha_desde, NEW.resolucion,
        NEW.created_by_user_id, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.codigo, OLD.version, OLD.nombre, OLD.categoria, OLD.motivo_exencion,
        OLD.aclaracion, OLD.sinonimos, OLD.orden, OLD.fecha_desde, OLD.resolucion,
        OLD.created_by_user_id, OLD.created_at)
       OR (NEW.fecha_hasta IS DISTINCT FROM OLD.fecha_hasta AND OLD.fecha_hasta IS NOT NULL) THEN
        RAISE EXCEPTION 'ddjj_vademecum: una versión no se modifica (se agrega otra)'
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
    # Motor paramétrico: criterio de pluralidad.
    op.drop_constraint(
        op.f("ck_parametros_conceptos_tipo_valido"), "parametros_conceptos", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_parametros_conceptos_tipo_valido"), "parametros_conceptos", f"tipo IN ({TIPOS})"
    )
    op.add_column(
        "parametros_vigencias", sa.Column("criterio", sa.String(length=40), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_parametros_vigencias_criterio"),
        "parametros_vigencias",
        "criterio IS NULL OR criterio IN "
        "('SOLO_EL_MAYOR', 'SUMAN_TODOS', 'VARIABLES_SUMAN_FIJO_UNA_VEZ')",
    )
    op.execute(_guard_vigencias(con_criterio=True))

    # Vademécum.
    op.create_table(
        "ddjj_vademecum",
        sa.Column("codigo", sa.String(length=60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("categoria", sa.String(length=30), nullable=False),
        sa.Column("motivo_exencion", sa.String(length=30), nullable=True),
        sa.Column("aclaracion", sa.Text(), nullable=True),
        sa.Column("sinonimos", sa.String(length=500), nullable=True),
        sa.Column("orden", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fecha_desde", sa.Date(), nullable=False),
        sa.Column("fecha_hasta", sa.Date(), nullable=True),
        sa.Column("resolucion", sa.String(length=150), nullable=False),
        sa.Column(
            "estado", sa.String(length=30), server_default="PENDIENTE_APROBACION", nullable=False
        ),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("aprobado_por_user_id", sa.UUID(), nullable=True),
        sa.Column("fecha_aprobacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE_APROBACION', 'VIGENTE', 'RECHAZADA')",
            name=op.f("ck_ddjj_vademecum_estado_valido"),
        ),
        sa.CheckConstraint(
            "(estado = 'VIGENTE') = (aprobado_por_user_id IS NOT NULL)",
            name=op.f("ck_ddjj_vademecum_aprobacion"),
        ),
        sa.CheckConstraint(
            "aprobado_por_user_id IS NULL OR aprobado_por_user_id <> created_by_user_id",
            name=op.f("ck_ddjj_vademecum_cuatro_ojos"),
        ),
        sa.CheckConstraint(
            "fecha_hasta IS NULL OR estado = 'VIGENTE'",
            name=op.f("ck_ddjj_vademecum_cierre_aprobada"),
        ),
        sa.CheckConstraint(
            "codigo ~ '^[A-Z][A-Z0-9_]{2,59}$'", name=op.f("ck_ddjj_vademecum_codigo_formato")
        ),
        sa.CheckConstraint(
            "categoria IN ('ESCRITURA_CON_VALOR', 'ACTA_O_PODER', 'OTRO_ACTO', 'EXENTO')",
            name=op.f("ck_ddjj_vademecum_categoria_valida"),
        ),
        sa.CheckConstraint(
            "(categoria = 'EXENTO') = (motivo_exencion IS NOT NULL)",
            name=op.f("ck_ddjj_vademecum_exento_con_motivo"),
        ),
        sa.CheckConstraint(
            "motivo_exencion IS NULL OR motivo_exencion IN ('CONVENIO_IPV', 'ACTA_SUBSANATORIA', "
            "'REGULACION_DOMINIAL', 'ASOCIACION_INTERMEDIA_IPV')",
            name=op.f("ck_ddjj_vademecum_motivo_exencion"),
        ),
        sa.CheckConstraint(
            "fecha_hasta IS NULL OR fecha_hasta >= fecha_desde",
            name=op.f("ck_ddjj_vademecum_rango_valido"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_ddjj_vademecum_version")),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["security_users.id"],
            name=op.f("fk_ddjj_vademecum_created_by_user_id_security_users"),
        ),
        sa.ForeignKeyConstraint(
            ["aprobado_por_user_id"],
            ["security_users.id"],
            name=op.f("fk_ddjj_vademecum_aprobado_por_user_id_security_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ddjj_vademecum")),
    )
    op.create_index(op.f("ix_ddjj_vademecum_codigo"), "ddjj_vademecum", ["codigo"], unique=False)
    op.create_index(op.f("ix_ddjj_vademecum_estado"), "ddjj_vademecum", ["estado"], unique=False)
    op.create_index(
        "uq_ddjj_vademecum_codigo_version", "ddjj_vademecum", ["codigo", "version"], unique=True
    )
    # Dos versiones aprobadas del mismo acto nunca rigen el mismo día.
    op.execute(
        "ALTER TABLE ddjj_vademecum ADD CONSTRAINT ex_ddjj_vademecum_sin_solapamiento "
        "EXCLUDE USING gist (codigo WITH =, daterange(fecha_desde, fecha_hasta, '[]') WITH &&) "
        "WHERE (estado = 'VIGENTE')"
    )
    op.execute(VADEMECUM_GUARD)
    op.execute(
        "CREATE TRIGGER ddjj_vademecum_guard BEFORE UPDATE OR DELETE ON ddjj_vademecum "
        "FOR EACH ROW EXECUTE FUNCTION ddjj_vademecum_guard()"
    )
    op.execute(
        "CREATE TRIGGER ddjj_vademecum_no_truncate BEFORE TRUNCATE ON ddjj_vademecum "
        "FOR EACH STATEMENT EXECUTE FUNCTION ddjj_vademecum_guard()"
    )
    _revoke_from_app_roles("ddjj_vademecum", "DELETE, TRUNCATE")

    # Actos.
    op.add_column("ddjj_actos", sa.Column("vademecum_id", sa.UUID(), nullable=True))
    op.add_column(
        "ddjj_actos",
        sa.Column("fuera_de_vademecum", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "ddjj_actos", sa.Column("precio", sa.Numeric(precision=18, scale=2), nullable=True)
    )
    op.add_column(
        "ddjj_actos", sa.Column("avaluo", sa.Numeric(precision=18, scale=2), nullable=True)
    )
    op.add_column(
        "ddjj_actos",
        sa.Column("mismas_partes", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "ddjj_actos",
        sa.Column("aporte_individual", sa.Numeric(precision=15, scale=2), nullable=True),
    )
    op.add_column("ddjj_actos", sa.Column("vigencia_pluralidad_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ddjj_actos_vademecum_id_ddjj_vademecum"),
        "ddjj_actos",
        "ddjj_vademecum",
        ["vademecum_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_ddjj_actos_vigencia_pluralidad_id_parametros_vigencias"),
        "ddjj_actos",
        "parametros_vigencias",
        ["vigencia_pluralidad_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_ddjj_actos_base_es_el_mayor"),
        "ddjj_actos",
        "(precio IS NULL AND avaluo IS NULL) OR (categoria = 'ESCRITURA_CON_VALOR' "
        "AND base_imponible = GREATEST(COALESCE(precio, 0), COALESCE(avaluo, 0)))",
    )
    op.create_check_constraint(
        op.f("ck_ddjj_actos_precio"), "ddjj_actos", "precio IS NULL OR precio >= 0"
    )
    op.create_check_constraint(
        op.f("ck_ddjj_actos_avaluo"), "ddjj_actos", "avaluo IS NULL OR avaluo >= 0"
    )
    op.create_check_constraint(
        op.f("ck_ddjj_actos_fuera_de_vademecum"),
        "ddjj_actos",
        "NOT (fuera_de_vademecum AND vademecum_id IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_ddjj_actos_aporte_individual"),
        "ddjj_actos",
        "aporte_individual IS NULL OR aporte IS NOT NULL",
    )
    op.drop_constraint(op.f("ck_ddjj_actos_motivo_exencion"), "ddjj_actos", type_="check")
    op.create_check_constraint(
        op.f("ck_ddjj_actos_motivo_exencion"),
        "ddjj_actos",
        f"motivo_exencion IS NULL OR motivo_exencion IN ({MOTIVOS})",
    )


def downgrade() -> None:
    # Volver atrás perdería cómo se valorizaron actos declarados: se niega si ya hay alguno.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM ddjj_actos
                       WHERE vademecum_id IS NOT NULL OR fuera_de_vademecum
                          OR precio IS NOT NULL OR avaluo IS NOT NULL
                          OR NOT mismas_partes OR aporte_individual IS NOT NULL
                          OR motivo_exencion IN ('REGULACION_DOMINIAL', 'ASOCIACION_INTERMEDIA_IPV'))
               OR EXISTS (SELECT 1 FROM parametros_conceptos WHERE tipo = 'CRITERIO_PLURALIDAD') THEN
                RAISE EXCEPTION 'Hay actos valorizados con el vademécum o un criterio de '
                    'pluralidad cargado: no se puede volver atrás sin perder esos datos.';
            END IF;
        END
        $$;
        """
    )
    op.drop_constraint(op.f("ck_ddjj_actos_motivo_exencion"), "ddjj_actos", type_="check")
    op.create_check_constraint(
        op.f("ck_ddjj_actos_motivo_exencion"),
        "ddjj_actos",
        f"motivo_exencion IS NULL OR motivo_exencion IN ({MOTIVOS_ANTES})",
    )
    for nombre in (
        "ck_ddjj_actos_aporte_individual",
        "ck_ddjj_actos_fuera_de_vademecum",
        "ck_ddjj_actos_avaluo",
        "ck_ddjj_actos_precio",
        "ck_ddjj_actos_base_es_el_mayor",
    ):
        op.drop_constraint(op.f(nombre), "ddjj_actos", type_="check")
    op.drop_constraint(
        op.f("fk_ddjj_actos_vigencia_pluralidad_id_parametros_vigencias"),
        "ddjj_actos",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_ddjj_actos_vademecum_id_ddjj_vademecum"), "ddjj_actos", type_="foreignkey"
    )
    for columna in (
        "vigencia_pluralidad_id",
        "aporte_individual",
        "mismas_partes",
        "avaluo",
        "precio",
        "fuera_de_vademecum",
        "vademecum_id",
    ):
        op.drop_column("ddjj_actos", columna)

    op.execute("DROP TABLE ddjj_vademecum")
    op.execute("DROP FUNCTION ddjj_vademecum_guard()")

    op.execute(_guard_vigencias(con_criterio=False))
    op.drop_constraint(
        op.f("ck_parametros_vigencias_criterio"), "parametros_vigencias", type_="check"
    )
    op.drop_column("parametros_vigencias", "criterio")
    op.drop_constraint(
        op.f("ck_parametros_conceptos_tipo_valido"), "parametros_conceptos", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_parametros_conceptos_tipo_valido"),
        "parametros_conceptos",
        f"tipo IN ({TIPOS_ANTES})",
    )
