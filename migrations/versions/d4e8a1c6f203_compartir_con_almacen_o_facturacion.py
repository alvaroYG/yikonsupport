"""compartir un mensaje con Almacén o con Facturación (roles nuevos, 14/10/2026)

Revision ID: d4e8a1c6f203
Revises: c1d7e5a3b902
Create Date: 2026-10-14 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e8a1c6f203'
down_revision = 'c1d7e5a3b902'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mensajes') as batch_op:
        batch_op.add_column(sa.Column('compartido_con', sa.String(length=40), nullable=True))
    # Lo que ya estaba compartido lo estaba con Logística, que ahora es Almacén
    op.execute("UPDATE mensajes SET compartido_con = 'logistica' WHERE compartido_el IS NOT NULL")


def downgrade():
    with op.batch_alter_table('mensajes') as batch_op:
        batch_op.drop_column('compartido_con')
