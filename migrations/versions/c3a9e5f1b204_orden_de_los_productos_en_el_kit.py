"""orden de los productos dentro de cada kit (elegido a mano en el formulario)

Los kits que ya existen conservan el orden que tenían (el de creación): orden = id.

Revision ID: c3a9e5f1b204
Revises: 18468d302915
Create Date: 2026-09-30 11:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3a9e5f1b204'
down_revision = '18468d302915'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('componentes_kit', schema=None) as batch_op:
        batch_op.add_column(sa.Column('orden', sa.Integer(), server_default='0', nullable=False))
    op.execute("UPDATE componentes_kit SET orden = id")


def downgrade():
    with op.batch_alter_table('componentes_kit', schema=None) as batch_op:
        batch_op.drop_column('orden')
