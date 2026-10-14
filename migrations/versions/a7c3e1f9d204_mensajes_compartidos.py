"""mensajes: compartir con Logística un mensaje de la conversación general (privada con el Soporte)

Revision ID: a7c3e1f9d204
Revises: f6a2d8c4e157
Create Date: 2026-10-09 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7c3e1f9d204'
down_revision = 'f6a2d8c4e157'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mensajes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('compartido_el', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('compartido_por_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('compartido_nota', sa.String(length=500), nullable=True))
        batch_op.create_foreign_key('fk_mensajes_compartido_por', 'usuarios', ['compartido_por_id'], ['id'])


def downgrade():
    with op.batch_alter_table('mensajes', schema=None) as batch_op:
        batch_op.drop_constraint('fk_mensajes_compartido_por', type_='foreignkey')
        batch_op.drop_column('compartido_nota')
        batch_op.drop_column('compartido_por_id')
        batch_op.drop_column('compartido_el')
