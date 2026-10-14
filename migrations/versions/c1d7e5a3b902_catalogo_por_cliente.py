"""catálogo propio de cada cliente: qué kits puede pedir y qué productos ve

Revision ID: c1d7e5a3b902
Revises: b913c0e10213
Create Date: 2026-10-13 14:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c1d7e5a3b902'
down_revision = 'b913c0e10213'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clientes') as batch_op:
        batch_op.add_column(sa.Column('catalogo_propio', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        'catalogo_kits',
        sa.Column('cliente_id', sa.Integer(), nullable=False),
        sa.Column('kit_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name='fk_catalogo_kits_cliente_id_clientes'),
        sa.ForeignKeyConstraint(['kit_id'], ['kits.id'], name='fk_catalogo_kits_kit_id_kits'),
        sa.PrimaryKeyConstraint('cliente_id', 'kit_id'),
    )
    op.create_table(
        'catalogo_productos',
        sa.Column('cliente_id', sa.Integer(), nullable=False),
        sa.Column('producto_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name='fk_catalogo_productos_cliente_id_clientes'),
        sa.ForeignKeyConstraint(['producto_id'], ['productos.id'], name='fk_catalogo_productos_producto_id_productos'),
        sa.PrimaryKeyConstraint('cliente_id', 'producto_id'),
    )


def downgrade():
    op.drop_table('catalogo_productos')
    op.drop_table('catalogo_kits')
    with op.batch_alter_table('clientes') as batch_op:
        batch_op.drop_column('catalogo_propio')
