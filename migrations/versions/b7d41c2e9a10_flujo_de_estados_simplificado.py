"""flujo de estados simplificado (29/09/2026)

Pasa los pedidos que ya existen al flujo nuevo:
  solicitado  → aceptado (el cliente ya aceptó la proforma, o lo creó Yikon)
  confirmado  → en_preparacion si ya tiene fotos, si no aceptado (aún no se ha empezado)
  revisar     → en_preparacion (logistics lo devolvió: su última revisión es un rechazo)
  proforma_solicitada cuya última proforma tiene cambios pedidos → cambios_solicitados
"Validado" y "Entregado" no cambian de clave (ahora se llaman "Listo para enviar" y "Recibido").
Solo toca datos (no hay columnas nuevas).

Revision ID: b7d41c2e9a10
Revises: ef62fe5ac37f
Create Date: 2026-09-29 13:30:00
"""
from alembic import op


revision = 'b7d41c2e9a10'
down_revision = 'ef62fe5ac37f'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE pedidos SET estado = 'aceptado' WHERE estado = 'solicitado'")
    op.execute("UPDATE pedidos SET estado = 'en_preparacion' WHERE estado = 'confirmado' "
               "AND id IN (SELECT pedido_id FROM fotos_pedido)")
    op.execute("UPDATE pedidos SET estado = 'aceptado' WHERE estado = 'confirmado'")
    op.execute("UPDATE pedidos SET estado = 'en_preparacion' WHERE estado = 'revisar'")
    op.execute("UPDATE pedidos SET estado = 'cambios_solicitados' WHERE estado = 'proforma_solicitada' "
               "AND (SELECT estado FROM proformas WHERE proformas.pedido_id = pedidos.id "
               "     ORDER BY proformas.id DESC LIMIT 1) = 'cambios'")


def downgrade():
    # Vuelta aproximada al flujo anterior (lo que se "juntó" no se puede separar del todo)
    op.execute("UPDATE pedidos SET estado = 'proforma_solicitada' WHERE estado = 'cambios_solicitados'")
    op.execute("UPDATE pedidos SET estado = 'confirmado' WHERE estado = 'en_preparacion'")
    op.execute("UPDATE pedidos SET estado = 'solicitado' WHERE estado = 'aceptado'")
