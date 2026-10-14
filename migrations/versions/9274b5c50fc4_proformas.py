"""Proformas: presupuesto sin precios que el cliente acepta antes de hacer el pedido (foto fija de sus productos)

Revision ID: 9274b5c50fc4
Revises: e881c0063cd0
Create Date: 2026-09-29 08:54:19.178792

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9274b5c50fc4'
down_revision = 'e881c0063cd0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pedidos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('con_proforma', sa.Boolean(), server_default=sa.false(), nullable=False))

    op.create_table('proformas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('numero', sa.String(length=20), nullable=False),
    sa.Column('pedido_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('fecha', sa.DateTime(timezone=True), nullable=True),
    sa.Column('valida_hasta', sa.Date(), nullable=False),
    sa.Column('plazo_entrega', sa.String(length=120), nullable=True),
    sa.Column('notas', sa.Text(), nullable=True),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('creada_por_id', sa.Integer(), nullable=True),
    sa.Column('respondida_por_id', sa.Integer(), nullable=True),
    sa.Column('respondida_fecha', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['creada_por_id'], ['usuarios.id'], name=op.f('fk_proformas_creada_por_id_usuarios')),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], name=op.f('fk_proformas_pedido_id_pedidos')),
    sa.ForeignKeyConstraint(['respondida_por_id'], ['usuarios.id'], name=op.f('fk_proformas_respondida_por_id_usuarios')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_proformas')),
    sa.UniqueConstraint('numero', name=op.f('uq_proformas_numero'))
    )
    with op.batch_alter_table('proformas', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_proformas_pedido_id'), ['pedido_id'], unique=False)

    op.create_table('proforma_lineas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('proforma_id', sa.Integer(), nullable=False),
    sa.Column('orden', sa.Integer(), nullable=False),
    sa.Column('grupo', sa.String(length=250), nullable=True),
    sa.Column('referencia', sa.String(length=50), nullable=False),
    sa.Column('nombre', sa.String(length=200), nullable=False),
    sa.Column('marca', sa.String(length=80), nullable=True),
    sa.Column('cantidad', sa.Integer(), nullable=False),
    sa.Column('caducidad', sa.Date(), nullable=True),
    sa.Column('sin_stock', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.ForeignKeyConstraint(['proforma_id'], ['proformas.id'], name=op.f('fk_proforma_lineas_proforma_id_proformas')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_proforma_lineas'))
    )
    with op.batch_alter_table('proforma_lineas', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_proforma_lineas_proforma_id'), ['proforma_id'], unique=False)



def downgrade():
    with op.batch_alter_table('pedidos', schema=None) as batch_op:
        batch_op.drop_column('con_proforma')

    with op.batch_alter_table('proforma_lineas', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_proforma_lineas_proforma_id'))

    op.drop_table('proforma_lineas')
    with op.batch_alter_table('proformas', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_proformas_pedido_id'))

    op.drop_table('proformas')
