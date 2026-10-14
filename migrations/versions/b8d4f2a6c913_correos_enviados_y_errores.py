"""registro de correos enviados y de errores de la web (Administración → Correos enviados / Estado)

Revision ID: b8d4f2a6c913
Revises: a7c3e1f9d204
Create Date: 2026-10-09 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8d4f2a6c913'
down_revision = 'a7c3e1f9d204'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'correos_enviados',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.DateTime(timezone=True), nullable=True),
        sa.Column('para', sa.Text(), nullable=False),
        sa.Column('asunto', sa.String(length=300), nullable=False),
        sa.Column('tipo', sa.String(length=60), nullable=True),
        sa.Column('cliente_id', sa.Integer(), nullable=True),
        sa.Column('pedido_id', sa.Integer(), nullable=True),
        sa.Column('estado', sa.String(length=10), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('texto', sa.Text(), nullable=True),
        sa.Column('html', sa.Text(), nullable=True),
        sa.Column('reenvio_de_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name='fk_correos_enviados_cliente'),
        sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], name='fk_correos_enviados_pedido'),
        sa.ForeignKeyConstraint(['reenvio_de_id'], ['correos_enviados.id'], name='fk_correos_enviados_reenvio'),
        sa.PrimaryKeyConstraint('id'),
    )
    for col in ('fecha', 'tipo', 'cliente_id', 'pedido_id'):
        op.create_index(f'ix_correos_enviados_{col}', 'correos_enviados', [col])
    op.create_table(
        'errores_web',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ruta', sa.String(length=300), nullable=True),
        sa.Column('usuario', sa.String(length=150), nullable=True),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_errores_web_fecha', 'errores_web', ['fecha'])


def downgrade():
    op.drop_index('ix_errores_web_fecha', table_name='errores_web')
    op.drop_table('errores_web')
    for col in ('fecha', 'tipo', 'cliente_id', 'pedido_id'):
        op.drop_index(f'ix_correos_enviados_{col}', table_name='correos_enviados')
    op.drop_table('correos_enviados')
