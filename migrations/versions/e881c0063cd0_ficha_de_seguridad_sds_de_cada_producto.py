"""Ficha de datos de seguridad (SDS) en PDF de cada producto, para que la descarguen los clientes

Revision ID: e881c0063cd0
Revises: 77102372eb1d
Create Date: 2026-09-29 08:41:05.826432

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e881c0063cd0'
down_revision = '77102372eb1d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('productos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sds_archivo', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('sds_nombre', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('sds_tamano', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('sds_fecha', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint(batch_op.f('uq_productos_sds_archivo'), ['sds_archivo'])



def downgrade():
    with op.batch_alter_table('productos', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uq_productos_sds_archivo'), type_='unique')
        batch_op.drop_column('sds_fecha')
        batch_op.drop_column('sds_tamano')
        batch_op.drop_column('sds_nombre')
        batch_op.drop_column('sds_archivo')

