"""ajustes de la plataforma (plazos de aviso editables por admin)

Revision ID: c4d1e7a90b12
Revises: ab067859e90d
Create Date: 2026-10-07 15:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4d1e7a90b12'
down_revision = 'ab067859e90d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ajustes',
    sa.Column('clave', sa.String(length=60), nullable=False),
    sa.Column('valor', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('clave')
    )


def downgrade():
    op.drop_table('ajustes')
