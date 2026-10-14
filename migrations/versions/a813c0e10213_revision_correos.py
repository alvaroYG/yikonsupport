"""Borradores de correo sujetos a revisión del autor.
Revision ID: a813c0e10213
Revises: c3e7a9d15f02
"""
from alembic import op
import sqlalchemy as sa
revision = "a813c0e10213"
down_revision = "c3e7a9d15f02"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("correos_borrador",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("autor_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
        sa.Column("caduca", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("mensaje", sa.LargeBinary()),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("reenvio_de_id", sa.Integer()),
        sa.Column("version", sa.Integer(), nullable=False))
    op.create_index("ix_correos_borrador_autor_id", "correos_borrador", ["autor_id"])
    op.create_index("ix_correos_borrador_estado", "correos_borrador", ["estado"])

def downgrade():
    op.drop_table("correos_borrador")
