"""datos de facturación y de envío del cliente; datos del albarán en el pedido (15/10/2026)

Revision ID: a3d8f2b6c914
Revises: f1c9d3e7a258
Create Date: 2026-10-15 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3d8f2b6c914'
down_revision = 'f1c9d3e7a258'
branch_labels = None
depends_on = None

CLIENTE = [
    ('codigo_postal', sa.String(12)), ('provincia', sa.String(100)), ('pais', sa.String(80)),
    ('envio_destinatario', sa.String(200)), ('envio_contacto', sa.String(120)), ('envio_telefono', sa.String(30)),
    ('envio_direccion', sa.String(250)), ('envio_codigo_postal', sa.String(12)), ('envio_ciudad', sa.String(100)),
    ('envio_provincia', sa.String(100)), ('envio_pais', sa.String(80)), ('envio_instrucciones', sa.Text()),
]


def upgrade():
    with op.batch_alter_table('clientes') as batch_op:
        for nombre, tipo in CLIENTE:
            batch_op.add_column(sa.Column(nombre, tipo, nullable=True))
        batch_op.add_column(sa.Column('envio_igual', sa.Boolean(), nullable=False, server_default=sa.true()))
    with op.batch_alter_table('pedidos') as batch_op:
        batch_op.add_column(sa.Column('datos_albaran', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('pedidos') as batch_op:
        batch_op.drop_column('datos_albaran')
    with op.batch_alter_table('clientes') as batch_op:
        batch_op.drop_column('envio_igual')
        for nombre, _tipo in reversed(CLIENTE):
            batch_op.drop_column(nombre)
