"""Opción por cliente: sus usuarios ven (o no) los precios en la plataforma

Revision ID: 2e5af7cf43fd
Revises: 9274b5c50fc4
Create Date: 2026-09-29 10:00:31.220269

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2e5af7cf43fd'
down_revision = '9274b5c50fc4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ver_precios', sa.Boolean(), server_default=sa.false(), nullable=False))



def downgrade():
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.drop_column('ver_precios')

