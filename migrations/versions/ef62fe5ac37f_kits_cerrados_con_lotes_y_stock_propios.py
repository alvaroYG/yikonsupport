"""kits cerrados con lotes y stock propios

Revision ID: ef62fe5ac37f
Revises: 2e5af7cf43fd
Create Date: 2026-09-29 12:19:30.675525

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ef62fe5ac37f'
down_revision = '2e5af7cf43fd'
branch_labels = None
depends_on = None


def upgrade():
    # Los kits que ya existen pasan a "cerrados" (lo normal según almacén): empiezan
    # sin stock propio; el stock que hubiera en sus productos se queda en los productos.
    with op.batch_alter_table('kits', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cerrado', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.add_column(sa.Column('stock_minimo', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('lotes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kit_id', sa.Integer(), nullable=True))
        batch_op.alter_column('producto_id',
               existing_type=sa.INTEGER(),
               nullable=True)
        batch_op.create_index(batch_op.f('ix_lotes_kit_id'), ['kit_id'], unique=False)
        batch_op.create_unique_constraint(batch_op.f('uq_lotes_kit_id'), ['kit_id', 'codigo'])
        batch_op.create_foreign_key(batch_op.f('fk_lotes_kit_id_kits'), 'kits', ['kit_id'], ['id'])
        # cada lote es de un producto O de un kit, nunca de los dos ni de ninguno
        batch_op.create_check_constraint(batch_op.f('ck_lotes_lote_de_producto_o_kit'),
                                         "(producto_id IS NULL) <> (kit_id IS NULL)")

    with op.batch_alter_table('movimientos_inventario', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kit_id', sa.Integer(), nullable=True))
        batch_op.alter_column('producto_id',
               existing_type=sa.INTEGER(),
               nullable=True)
        batch_op.create_index(batch_op.f('ix_movimientos_inventario_kit_id'), ['kit_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_movimientos_inventario_kit_id_kits'), 'kits', ['kit_id'], ['id'])



def downgrade():
    # Volver atrás borra el inventario de los kits cerrados (antes no existía)
    op.execute("DELETE FROM movimientos_inventario WHERE kit_id IS NOT NULL")
    op.execute("DELETE FROM lotes WHERE kit_id IS NOT NULL")
    with op.batch_alter_table('movimientos_inventario', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_movimientos_inventario_kit_id_kits'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_movimientos_inventario_kit_id'))
        batch_op.alter_column('producto_id',
               existing_type=sa.INTEGER(),
               nullable=False)
        batch_op.drop_column('kit_id')

    with op.batch_alter_table('lotes', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('ck_lotes_lote_de_producto_o_kit'), type_='check')
        batch_op.drop_constraint(batch_op.f('fk_lotes_kit_id_kits'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('uq_lotes_kit_id'), type_='unique')
        batch_op.drop_index(batch_op.f('ix_lotes_kit_id'))
        batch_op.alter_column('producto_id',
               existing_type=sa.INTEGER(),
               nullable=False)
        batch_op.drop_column('kit_id')

    with op.batch_alter_table('kits', schema=None) as batch_op:
        batch_op.drop_column('stock_minimo')
        batch_op.drop_column('cerrado')

