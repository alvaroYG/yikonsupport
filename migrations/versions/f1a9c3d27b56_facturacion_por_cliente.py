"""facturación por cliente: formato de factura, régimen de IVA y gastos de envío pactados

Revision ID: f1a9c3d27b56
Revises: e5b7a1c94f20
Create Date: 2026-10-08 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a9c3d27b56'
down_revision = 'e5b7a1c94f20'
branch_labels = None
depends_on = None


def upgrade():
    # Vacíos = sin configurar: "Datos para facturar" usa formato A, IVA España y sin envío, y lo avisa
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('formato_factura', sa.String(length=1), nullable=True))
        batch_op.add_column(sa.Column('regimen_iva', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('gastos_envio', sa.Numeric(10, 2), nullable=True))


def downgrade():
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.drop_column('gastos_envio')
        batch_op.drop_column('regimen_iva')
        batch_op.drop_column('formato_factura')
