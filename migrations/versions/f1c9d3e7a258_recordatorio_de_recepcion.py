"""recordatorio automático «¿Ha recibido el pedido?» (15/10/2026)

Revision ID: f1c9d3e7a258
Revises: e2a7c5b91d04
Create Date: 2026-10-15 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f1c9d3e7a258'
down_revision = 'e2a7c5b91d04'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pedidos') as batch_op:
        batch_op.add_column(sa.Column('recordatorio_recibido_el', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('pedidos') as batch_op:
        batch_op.drop_column('recordatorio_recibido_el')
