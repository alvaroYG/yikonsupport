"""factura en Excel completa: HS Code de cada producto y EORI del cliente (15/10/2026)

Revision ID: d4b8e6a1f725
Revises: c7f2a9d4e318
Create Date: 2026-10-15 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4b8e6a1f725'
down_revision = 'c7f2a9d4e318'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('productos') as batch_op:
        batch_op.add_column(sa.Column('codigo_hs', sa.String(20), nullable=True))
    with op.batch_alter_table('clientes') as batch_op:
        batch_op.add_column(sa.Column('eori', sa.String(20), nullable=True))
    # Los productos que ya había: el de la plantilla de factura (se cambia en cada producto)
    productos = sa.table('productos', sa.column('codigo_hs', sa.String))
    op.execute(productos.update().values(codigo_hs='3822190090'))


def downgrade():
    with op.batch_alter_table('clientes') as batch_op:
        batch_op.drop_column('eori')
    with op.batch_alter_table('productos') as batch_op:
        batch_op.drop_column('codigo_hs')
