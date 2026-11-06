"""lineas_credito_moneda: moneda (pesos o dólares) y requisitos de las líneas de crédito

Las líneas reales de la Caja (Resolución N° 273) incluyen dos en dólares y requisitos de
garantía, certificados y antigüedad en la matrícula. El préstamo copia la moneda de su línea al
solicitarse y no la cambia nunca (trigger).

Revision ID: b8f61c8f2577
Revises: b4e8c2a61d07
Create Date: 2026-11-06 08:56:07.436565

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8f61c8f2577"
down_revision: str | None = "b4e8c2a61d07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEDA_VALIDA = "moneda IN ('ARS', 'USD')"

MONEDA_GUARD_FN = """
CREATE OR REPLACE FUNCTION prestamos_moneda_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.moneda IS DISTINCT FROM OLD.moneda THEN
        RAISE EXCEPTION 'prestamos: la moneda de un préstamo no cambia'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.add_column(
        "prestamos",
        sa.Column("moneda", sa.String(length=3), server_default="ARS", nullable=False),
    )
    op.add_column(
        "prestamos_lineas",
        sa.Column("moneda", sa.String(length=3), server_default="ARS", nullable=False),
    )
    op.add_column("prestamos_lineas", sa.Column("garantia", sa.Text(), nullable=True))
    op.add_column("prestamos_lineas", sa.Column("requisito_conducta", sa.Text(), nullable=True))
    op.add_column(
        "prestamos_lineas",
        sa.Column("relacion_capital_hipoteca", sa.Numeric(precision=18, scale=4), nullable=True),
    )
    op.add_column(
        "prestamos_lineas",
        sa.Column(
            "requiere_certificado_ingresos", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column(
        "prestamos_lineas",
        sa.Column(
            "requiere_certificado_bienes", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column(
        "prestamos_lineas", sa.Column("antiguedad_minima_meses", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(op.f("ck_prestamos_moneda"), "prestamos", MONEDA_VALIDA)
    op.create_check_constraint(
        op.f("ck_prestamos_lineas_moneda"), "prestamos_lineas", MONEDA_VALIDA
    )
    op.create_check_constraint(
        op.f("ck_prestamos_lineas_relacion_capital_hipoteca"),
        "prestamos_lineas",
        "relacion_capital_hipoteca IS NULL OR "
        "(relacion_capital_hipoteca > 0 AND relacion_capital_hipoteca <= 100)",
    )
    op.create_check_constraint(
        op.f("ck_prestamos_lineas_antiguedad_minima"),
        "prestamos_lineas",
        "antiguedad_minima_meses IS NULL OR antiguedad_minima_meses > 0",
    )
    op.execute(MONEDA_GUARD_FN)
    op.execute(
        "CREATE TRIGGER prestamos_moneda_guard BEFORE UPDATE OF moneda ON prestamos "
        "FOR EACH ROW EXECUTE FUNCTION prestamos_moneda_guard()"
    )


def downgrade() -> None:
    # Sin columna de moneda, un préstamo en dólares se leería como pesos: no se vuelve atrás
    # mientras haya líneas o préstamos en dólares.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM prestamos WHERE moneda <> 'ARS')
               OR EXISTS (SELECT 1 FROM prestamos_lineas WHERE moneda <> 'ARS') THEN
                RAISE EXCEPTION 'Hay líneas o préstamos en dólares: no se puede quitar la moneda.';
            END IF;
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS prestamos_moneda_guard ON prestamos")
    op.execute("DROP FUNCTION IF EXISTS prestamos_moneda_guard()")
    op.drop_constraint(
        op.f("ck_prestamos_lineas_antiguedad_minima"), "prestamos_lineas", type_="check"
    )
    op.drop_constraint(
        op.f("ck_prestamos_lineas_relacion_capital_hipoteca"), "prestamos_lineas", type_="check"
    )
    op.drop_constraint(op.f("ck_prestamos_lineas_moneda"), "prestamos_lineas", type_="check")
    op.drop_constraint(op.f("ck_prestamos_moneda"), "prestamos", type_="check")
    op.drop_column("prestamos_lineas", "antiguedad_minima_meses")
    op.drop_column("prestamos_lineas", "requiere_certificado_bienes")
    op.drop_column("prestamos_lineas", "requiere_certificado_ingresos")
    op.drop_column("prestamos_lineas", "relacion_capital_hipoteca")
    op.drop_column("prestamos_lineas", "requisito_conducta")
    op.drop_column("prestamos_lineas", "garantia")
    op.drop_column("prestamos_lineas", "moneda")
    op.drop_column("prestamos", "moneda")
