"""PDF oficial de las facturas (para que lo descargue el cliente) y archivos adjuntos en los mensajes

Revision ID: 77102372eb1d
Revises: acd559655956
Create Date: 2026-09-28 13:32:14.448424

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '77102372eb1d'
down_revision = 'acd559655956'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('adjuntos_mensaje',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('mensaje_id', sa.Integer(), nullable=False),
    sa.Column('archivo', sa.String(length=100), nullable=False),
    sa.Column('nombre_original', sa.String(length=200), nullable=False),
    sa.Column('tamano', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['mensaje_id'], ['mensajes.id'], name=op.f('fk_adjuntos_mensaje_mensaje_id_mensajes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_adjuntos_mensaje')),
    sa.UniqueConstraint('archivo', name=op.f('uq_adjuntos_mensaje_archivo'))
    )
    with op.batch_alter_table('adjuntos_mensaje', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_adjuntos_mensaje_mensaje_id'), ['mensaje_id'], unique=False)

    with op.batch_alter_table('facturas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pdf_archivo', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('pdf_nombre', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('pdf_tamano', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(batch_op.f('uq_facturas_pdf_archivo'), ['pdf_archivo'])



def downgrade():
    with op.batch_alter_table('facturas', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uq_facturas_pdf_archivo'), type_='unique')
        batch_op.drop_column('pdf_tamano')
        batch_op.drop_column('pdf_nombre')
        batch_op.drop_column('pdf_archivo')

    with op.batch_alter_table('adjuntos_mensaje', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_adjuntos_mensaje_mensaje_id'))

    op.drop_table('adjuntos_mensaje')
