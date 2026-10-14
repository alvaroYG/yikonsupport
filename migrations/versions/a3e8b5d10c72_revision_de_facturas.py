"""revisión de facturas por Soporte de cliente y envío al cliente

Revision ID: a3e8b5d10c72
Revises: f1a9c3d27b56
Create Date: 2026-10-08 12:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3e8b5d10c72'
down_revision = 'f1a9c3d27b56'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('facturas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('revision', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('revision_comentario', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('revisado_por_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('revisado_el', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('enviada_el', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key('fk_facturas_revisado_por', 'usuarios', ['revisado_por_id'], ['id'])
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('revisar_facturas', sa.Boolean(), nullable=False, server_default=sa.false()))
    # Las facturas que ya había el cliente ya las ve: cuentan como enviadas (cuando se registraron)
    op.execute("UPDATE facturas SET enviada_el = COALESCE(creado, CURRENT_TIMESTAMP)")


def downgrade():
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.drop_column('revisar_facturas')
    with op.batch_alter_table('facturas', schema=None) as batch_op:
        batch_op.drop_constraint('fk_facturas_revisado_por', type_='foreignkey')
        batch_op.drop_column('enviada_el')
        batch_op.drop_column('revisado_el')
        batch_op.drop_column('revisado_por_id')
        batch_op.drop_column('revision_comentario')
        batch_op.drop_column('revision')
