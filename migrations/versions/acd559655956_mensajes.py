"""Mensajes entre clientes y Yikon (conversación general por cliente y por pedido)

Revision ID: acd559655956
Revises: f72ff25fc233
Create Date: 2026-09-28 12:57:42.308113

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'acd559655956'
down_revision = 'f72ff25fc233'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('lecturas_hilo',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('hilo', sa.String(length=30), nullable=False),
    sa.Column('ultimo_mensaje_id', sa.Integer(), nullable=False),
    sa.Column('avisado', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], name=op.f('fk_lecturas_hilo_usuario_id_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lecturas_hilo')),
    sa.UniqueConstraint('usuario_id', 'hilo', name=op.f('uq_lecturas_hilo_usuario_id'))
    )
    with op.batch_alter_table('lecturas_hilo', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lecturas_hilo_usuario_id'), ['usuario_id'], unique=False)

    op.create_table('mensajes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hilo', sa.String(length=30), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.Column('pedido_id', sa.Integer(), nullable=True),
    sa.Column('autor_id', sa.Integer(), nullable=False),
    sa.Column('de_cliente', sa.Boolean(), nullable=False),
    sa.Column('texto', sa.Text(), nullable=False),
    sa.Column('fecha', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['autor_id'], ['usuarios.id'], name=op.f('fk_mensajes_autor_id_usuarios')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_mensajes_cliente_id_clientes')),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], name=op.f('fk_mensajes_pedido_id_pedidos')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mensajes'))
    )
    with op.batch_alter_table('mensajes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mensajes_cliente_id'), ['cliente_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mensajes_fecha'), ['fecha'], unique=False)
        batch_op.create_index(batch_op.f('ix_mensajes_hilo'), ['hilo'], unique=False)
        batch_op.create_index('ix_mensajes_hilo_lado_id', ['hilo', 'de_cliente', 'id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mensajes_pedido_id'), ['pedido_id'], unique=False)



def downgrade():
    with op.batch_alter_table('mensajes', schema=None) as batch_op:
        batch_op.drop_index('ix_mensajes_hilo_lado_id')
        batch_op.drop_index(batch_op.f('ix_mensajes_pedido_id'))
        batch_op.drop_index(batch_op.f('ix_mensajes_hilo'))
        batch_op.drop_index(batch_op.f('ix_mensajes_fecha'))
        batch_op.drop_index(batch_op.f('ix_mensajes_cliente_id'))

    op.drop_table('mensajes')
    with op.batch_alter_table('lecturas_hilo', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lecturas_hilo_usuario_id'))

    op.drop_table('lecturas_hilo')
