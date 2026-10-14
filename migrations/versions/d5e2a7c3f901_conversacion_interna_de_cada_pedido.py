"""conversación interna de cada pedido (solo admin y logistics)

Revision ID: d5e2a7c3f901
Revises: c3a9e5f1b204
Create Date: 2026-09-30 11:20:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'd5e2a7c3f901'
down_revision = 'c3a9e5f1b204'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mensajes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('interno', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    # Volver atrás borra las conversaciones internas (antes no existían y las vería el cliente)
    op.execute("DELETE FROM adjuntos_mensaje WHERE mensaje_id IN (SELECT id FROM mensajes WHERE interno)")
    op.execute("DELETE FROM mensajes WHERE interno")
    with op.batch_alter_table('mensajes', schema=None) as batch_op:
        batch_op.drop_column('interno')
