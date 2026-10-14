"""roles: logística, FAS y acceso a Soporte ChromGo por usuario

- Los usuarios con rol "logistics" pasan a ser "fas" (conservan sus clientes asignados).
  El rol "logistica" (la oficina) es nuevo: se asigna a mano desde Usuarios.
- El acceso a Soporte ChromGo de un usuario Cliente pasa de la empresa (clientes.usa_chromgo)
  al propio usuario (usuarios.acceso_chromgo). Los usuarios Cliente de las empresas que lo
  tenían marcado lo conservan.

Revision ID: 13f7b44dd422
Revises: 2b29a0814126
Create Date: 2026-09-30 13:12:33.619086

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '13f7b44dd422'
down_revision = '2b29a0814126'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('acceso_chromgo', sa.Boolean(), server_default=sa.false(), nullable=False))

    # Antes de borrar la casilla de la empresa: se la pasamos a sus usuarios Cliente
    op.execute("UPDATE usuarios SET acceso_chromgo = TRUE WHERE rol = 'cliente' AND cliente_id IN "
               "(SELECT id FROM clientes WHERE usa_chromgo = TRUE)")
    op.execute("UPDATE usuarios SET rol = 'fas' WHERE rol = 'logistics'")

    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.drop_column('usa_chromgo')


def downgrade():
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('usa_chromgo', sa.Boolean(), server_default=sa.false(), nullable=False))

    op.execute("UPDATE clientes SET usa_chromgo = TRUE WHERE id IN "
               "(SELECT cliente_id FROM usuarios WHERE acceso_chromgo = TRUE AND cliente_id IS NOT NULL)")
    # FAS vuelve a ser logistics; Logística (que no existía) también, para no dejar a nadie sin rol válido
    op.execute("UPDATE usuarios SET rol = 'logistics' WHERE rol IN ('fas', 'logistica')")

    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.drop_column('acceso_chromgo')
