"""uso del pedido (RUO / IVD / indiferente) y observaciones del cliente (15/10/2026)

Revision ID: e2a7c5b91d04
Revises: d4e8a1c6f203
Create Date: 2026-10-15 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e2a7c5b91d04'
down_revision = 'd4e8a1c6f203'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pedidos') as batch_op:
        batch_op.add_column(sa.Column('uso', sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column('observaciones', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('pedidos') as batch_op:
        batch_op.drop_column('observaciones')
        batch_op.drop_column('uso')
