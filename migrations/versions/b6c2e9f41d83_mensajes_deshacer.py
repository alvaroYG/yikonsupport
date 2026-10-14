"""mensajes de Yikon al cliente con unos segundos para deshacer

Revision ID: b6c2e9f41d83
Revises: a3e8b5d10c72
Create Date: 2026-10-08 15:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b6c2e9f41d83'
down_revision = 'a3e8b5d10c72'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mensajes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('visible_desde', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('mensajes', schema=None) as batch_op:
        batch_op.drop_column('visible_desde')
