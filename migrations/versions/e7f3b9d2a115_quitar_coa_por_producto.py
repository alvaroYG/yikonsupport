"""quitar el COA por producto (el COA va con cada pedido, en sus documentos)

El COA depende del lote, así que se adjunta en los documentos de cada pedido.
Esta migración deshace la 18468d302915 (COA de cada producto).

Revision ID: e7f3b9d2a115
Revises: d5e2a7c3f901
Create Date: 2026-09-30 11:40:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7f3b9d2a115'
down_revision = 'd5e2a7c3f901'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('productos', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uq_productos_coa_archivo'), type_='unique')
        batch_op.drop_column('coa_fecha')
        batch_op.drop_column('coa_tamano')
        batch_op.drop_column('coa_nombre')
        batch_op.drop_column('coa_archivo')


def downgrade():
    with op.batch_alter_table('productos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('coa_archivo', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('coa_nombre', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('coa_tamano', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('coa_fecha', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint(batch_op.f('uq_productos_coa_archivo'), ['coa_archivo'])
