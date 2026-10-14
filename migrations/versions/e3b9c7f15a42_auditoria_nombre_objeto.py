"""auditoría: nombre legible del objeto (en vez de solo "Pedido #23")

Revision ID: e3b9c7f15a42
Revises: d7a1e5c3b820
Create Date: 2026-10-08 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3b9c7f15a42'
down_revision = 'd7a1e5c3b820'
branch_labels = None
depends_on = None

# Para los registros que ya había: el nombre que tiene HOY cada objeto (los borrados se quedan
# sin nombre y la página enseña "#id"). "||" concatena en SQLite y en PostgreSQL.
RELLENAR = {
    "Pedido": "SELECT COALESCE(p.referencia_interna, '#' || p.id) || ' · ' || c.nombre FROM pedidos p "
              "JOIN clientes c ON c.id = p.cliente_id WHERE p.id = auditoria.entidad_id",
    "Cliente": "SELECT nombre FROM clientes WHERE id = auditoria.entidad_id",
    "User": "SELECT nombre || ' (' || email || ')' FROM usuarios WHERE id = auditoria.entidad_id",
    "Factura": "SELECT f.numero || ' · ' || c.nombre FROM facturas f JOIN clientes c ON c.id = f.cliente_id "
               "WHERE f.id = auditoria.entidad_id",
    "Producto": "SELECT referencia || ' · ' || nombre FROM productos WHERE id = auditoria.entidad_id",
    "Kit": "SELECT referencia || ' · ' || nombre FROM kits WHERE id = auditoria.entidad_id",
    "DocumentoInterno": "SELECT titulo FROM documentos_internos WHERE id = auditoria.entidad_id",
    "Ticket": "SELECT numero || ' · ' || asunto FROM tickets WHERE id = auditoria.entidad_id",
}


def upgrade():
    with op.batch_alter_table('auditoria', schema=None) as batch_op:
        batch_op.add_column(sa.Column('objeto', sa.String(length=250), nullable=True))
    for entidad, consulta in RELLENAR.items():
        op.execute(sa.text(f"UPDATE auditoria SET objeto = SUBSTR(({consulta}), 1, 250) "
                           "WHERE entidad = :entidad AND entidad_id IS NOT NULL").bindparams(entidad=entidad))


def downgrade():
    with op.batch_alter_table('auditoria', schema=None) as batch_op:
        batch_op.drop_column('objeto')
