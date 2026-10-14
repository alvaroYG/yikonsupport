"""ajustes: valor sin límite de largo (notas por defecto de las proformas, datos de Yikon)

Revision ID: f6a2d8c4e157
Revises: e3b9c7f15a42
Create Date: 2026-10-09 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f6a2d8c4e157'
down_revision = 'e3b9c7f15a42'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ajustes', schema=None) as batch_op:
        batch_op.alter_column('valor', existing_type=sa.String(length=200), type_=sa.Text(), existing_nullable=False)


def downgrade():
    with op.batch_alter_table('ajustes', schema=None) as batch_op:
        batch_op.alter_column('valor', existing_type=sa.Text(), type_=sa.String(length=200), existing_nullable=False)
