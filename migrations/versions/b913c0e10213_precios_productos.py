"""Precios especiales de productos sueltos por cliente."""
from alembic import op
import sqlalchemy as sa
revision = "b913c0e10213"
down_revision = "a813c0e10213"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("precios_producto_cliente",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("cliente_id",sa.Integer(),sa.ForeignKey("clientes.id"),nullable=False),
        sa.Column("producto_id",sa.Integer(),sa.ForeignKey("productos.id"),nullable=False),
        sa.Column("precio",sa.Numeric(10,2),nullable=False),
        sa.UniqueConstraint("cliente_id","producto_id"))
    op.create_index("ix_precios_producto_cliente_cliente_id","precios_producto_cliente",["cliente_id"])

def downgrade():
    op.drop_table("precios_producto_cliente")
