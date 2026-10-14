"""proformas: PDF que adjunta Yikon, comentario de cambios y número PF-{referencia}

Revision ID: c4f8d2a7e913
Revises: b6c2e9f41d83
Create Date: 2026-10-08 17:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4f8d2a7e913'
down_revision = 'b6c2e9f41d83'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('proformas', schema=None) as batch_op:
        batch_op.alter_column('numero', existing_type=sa.String(length=20), type_=sa.String(length=60),
                              existing_nullable=False)
        batch_op.add_column(sa.Column('comentario_cambios', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('pdf_archivo', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('pdf_nombre', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('pdf_tamano', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint('uq_proformas_pdf_archivo', ['pdf_archivo'])


def downgrade():
    with op.batch_alter_table('proformas', schema=None) as batch_op:
        batch_op.drop_constraint('uq_proformas_pdf_archivo', type_='unique')
        batch_op.drop_column('pdf_tamano')
        batch_op.drop_column('pdf_nombre')
        batch_op.drop_column('pdf_archivo')
        batch_op.drop_column('comentario_cambios')
        batch_op.alter_column('numero', existing_type=sa.String(length=60), type_=sa.String(length=20),
                              existing_nullable=False)
