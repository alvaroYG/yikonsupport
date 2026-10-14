"""paso 92: incidencias de pedidos, avisos por usuario del cliente (y emails en copia), aviso cerrado

Revision ID: c3e7a9d15f02
Revises: b8d4f2a6c913
Create Date: 2026-10-13 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3e7a9d15f02'
down_revision = 'b8d4f2a6c913'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('usuarios') as batch_op:
        batch_op.add_column(sa.Column('avisos_desactivados', sa.String(length=200), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('aviso_cerrado', sa.String(length=20), nullable=True))

    op.create_table(
        'copias_aviso',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cliente_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('tipos', sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name='fk_copias_aviso_cliente'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cliente_id', 'email', name='uq_copias_aviso_cliente_id'),
    )
    op.create_index('ix_copias_aviso_cliente_id', 'copias_aviso', ['cliente_id'])

    op.create_table(
        'incidencias',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pedido_id', sa.Integer(), nullable=False),
        sa.Column('motivo', sa.String(length=20), nullable=False),
        sa.Column('texto', sa.Text(), nullable=False),
        sa.Column('creada', sa.DateTime(timezone=True), nullable=True),
        sa.Column('creada_por_id', sa.Integer(), nullable=True),
        sa.Column('mensaje_id', sa.Integer(), nullable=True),
        sa.Column('estado', sa.String(length=10), nullable=False),
        sa.Column('resuelta_el', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resuelta_por_id', sa.Integer(), nullable=True),
        sa.Column('nota_resolucion', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], name='fk_incidencias_pedido'),
        sa.ForeignKeyConstraint(['creada_por_id'], ['usuarios.id'], name='fk_incidencias_creada_por'),
        sa.ForeignKeyConstraint(['mensaje_id'], ['mensajes.id'], name='fk_incidencias_mensaje'),
        sa.ForeignKeyConstraint(['resuelta_por_id'], ['usuarios.id'], name='fk_incidencias_resuelta_por'),
        sa.PrimaryKeyConstraint('id'),
    )
    for col in ('pedido_id', 'creada', 'estado'):
        op.create_index(f'ix_incidencias_{col}', 'incidencias', [col])


def downgrade():
    for col in ('pedido_id', 'creada', 'estado'):
        op.drop_index(f'ix_incidencias_{col}', table_name='incidencias')
    op.drop_table('incidencias')
    op.drop_index('ix_copias_aviso_cliente_id', table_name='copias_aviso')
    op.drop_table('copias_aviso')
    with op.batch_alter_table('usuarios') as batch_op:
        batch_op.drop_column('aviso_cerrado')
        batch_op.drop_column('avisos_desactivados')
