"""mapa de clientes: dónde está cada cliente (15/10/2026)

Revision ID: b5e1c7d9a206
Revises: a3d8f2b6c914
Create Date: 2026-10-15 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b5e1c7d9a206'
down_revision = 'a3d8f2b6c914'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clientes') as batch_op:
        batch_op.add_column(sa.Column('latitud', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('longitud', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('clientes') as batch_op:
        batch_op.drop_column('longitud')
        batch_op.drop_column('latitud')
