"""facturas sin importes: la factura se hace a mano fuera y aquí solo se registra (PDF, nº, vencimiento)

Revision ID: e5b7a1c94f20
Revises: d8a3f2c61e47
Create Date: 2026-10-08 09:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5b7a1c94f20'
down_revision = 'd8a3f2c61e47'
branch_labels = None
depends_on = None

COLUMNAS = ('base_imponible', 'iva', 'total')


def upgrade():
    # Las columnas se quedan (las facturas antiguas conservan sus importes), pero dejan de ser obligatorias
    with op.batch_alter_table('facturas', schema=None) as batch_op:
        for c in COLUMNAS:
            batch_op.alter_column(c, existing_type=sa.Numeric(12, 2), nullable=True)


def downgrade():
    op.execute("UPDATE facturas SET base_imponible = 0 WHERE base_imponible IS NULL")
    op.execute("UPDATE facturas SET iva = 0 WHERE iva IS NULL")
    op.execute("UPDATE facturas SET total = 0 WHERE total IS NULL")
    with op.batch_alter_table('facturas', schema=None) as batch_op:
        for c in COLUMNAS:
            batch_op.alter_column(c, existing_type=sa.Numeric(12, 2), nullable=False)
