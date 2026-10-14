"""correos al cliente editables desde Ajustes

Revision ID: d7a1e5c3b820
Revises: c4f8d2a7e913
Create Date: 2026-10-08 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7a1e5c3b820'
down_revision = 'c4f8d2a7e913'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'plantillas_correo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clave', sa.String(length=40), nullable=False),
        sa.Column('idioma', sa.String(length=5), nullable=False),
        sa.Column('asunto', sa.String(length=200), nullable=True),
        sa.Column('cuerpo', sa.Text(), nullable=False),
        sa.Column('actualizado_por_id', sa.Integer(), nullable=True),
        sa.Column('actualizado_el', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['actualizado_por_id'], ['usuarios.id'], name='fk_plantillas_correo_usuario'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clave', 'idioma', name='uq_plantillas_correo_clave_idioma'),
    )


def downgrade():
    op.drop_table('plantillas_correo')
