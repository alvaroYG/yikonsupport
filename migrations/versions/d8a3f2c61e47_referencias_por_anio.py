"""referencias de pedido por año: YK-<año>-<prefijo>-<número>

Revision ID: d8a3f2c61e47
Revises: c4d1e7a90b12
Create Date: 2026-10-08 08:45:00.000000

"""
from datetime import date

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8a3f2c61e47'
down_revision = 'c4d1e7a90b12'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('anio_contador', sa.Integer(), nullable=True))
    # Los clientes que ya tienen pedidos siguen contando este año donde iban (DiNA_004 → el
    # siguiente es YK-<año>-DiNA-5); el año que viene empiezan en 1.
    op.execute(f"UPDATE clientes SET anio_contador = {date.today().year} WHERE contador_pedidos > 0")


def downgrade():
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.drop_column('anio_contador')
