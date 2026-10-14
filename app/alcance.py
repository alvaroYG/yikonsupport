"""
ALCANCE: qué REGISTROS puede ver cada usuario.

permisos.py responde a "¿puede este rol ver pedidos?" (capa 1).
Este módulo responde a "¿CUÁLES?" (capa 2):

  - admin, logística → todos (Logística: la oficina, gestiona todos los pedidos)
  - FAS              → los de los clientes que tiene asignados
  - clientes         → los de su propia empresa

Regla de oro: toda consulta de clientes o pedidos que llegue a una vista pasa
por aquí. Si una vista hace db.get_or_404(Pedido, id) directamente, un cliente
podría ver pedidos ajenos cambiando el número de la URL.
"""
from flask import abort
from flask_login import current_user
from sqlalchemy import or_, false

from app.extensions import db
from app.models import Cliente, Factura, Mensaje, Pedido, User

# Ven los pedidos, mensajes y facturas de TODOS los clientes (el resto, solo los suyos).
# (Soporte ChromGo no está: no trabaja con pedidos; sus tickets van por soporte/servicio.py)
TODOS_LOS_CLIENTES = {"admin", "logistica"}


def filtrar_clientes(select):
    """Recibe un db.select(...) sobre Cliente y le añade el filtro del usuario actual."""
    u = current_user
    if u.rol in TODOS_LOS_CLIENTES:
        return select
    if u.rol == "fas":
        # "clientes cuya lista de logisticos contiene a este usuario"
        return select.where(Cliente.logisticos.any(User.id == u.id))
    if u.es_cliente:
        return select.where(Cliente.id == u.cliente_id)
    return select.where(false())  # rol desconocido: nada


def filtrar_pedidos(select):
    """Igual, sobre Pedido: un pedido es visible si su cliente es visible."""
    u = current_user
    if u.rol in TODOS_LOS_CLIENTES:
        return select
    if u.rol == "fas":
        return select.where(Pedido.cliente.has(Cliente.logisticos.any(User.id == u.id)))
    if u.es_cliente:
        return select.where(Pedido.cliente_id == u.cliente_id)
    return select.where(false())


def filtrar_mensajes(select):
    """Igual, sobre Mensaje: se ven los mensajes de los clientes que ves (general y de pedidos).
    Los INTERNOS (entre la gente de Yikon) no los ve nunca el cliente: se filtran aquí, en el único
    sitio por el que pasan todas las consultas de mensajes."""
    u = current_user
    if u.rol in TODOS_LOS_CLIENTES:
        if u.puede("mensajes.general"):
            return select
        # Logística: los de los pedidos y, de las conversaciones generales, solo lo compartido con ella
        return select.where(or_(Mensaje.pedido_id.isnot(None), Mensaje.compartido_el.isnot(None)))
    if u.rol == "fas":
        return select.where(Mensaje.cliente.has(Cliente.logisticos.any(User.id == u.id)))
    if u.es_cliente:
        return select.where(Mensaje.cliente_id == u.cliente_id, Mensaje.interno.is_(False), mensaje_ya_visible())
    return select.where(false())


def mensaje_ya_visible():
    """Condición: el mensaje ya se puede enseñar al cliente (no está en sus segundos de "deshacer")."""
    from app.models import ahora
    return or_(Mensaje.visible_desde.is_(None), Mensaje.visible_desde <= ahora())


def filtrar_facturas(select):
    """Igual, sobre Factura: el FAS solo las de sus clientes; el cliente, las de su empresa ya enviadas."""
    u = current_user
    if u.rol in TODOS_LOS_CLIENTES:
        return select
    if u.rol == "fas":
        return select.where(Factura.cliente.has(Cliente.logisticos.any(User.id == u.id)))
    if u.es_cliente:
        # Solo las que ya le hemos enviado (no las que están en revisión o por enviar)
        return select.where(Factura.cliente_id == u.cliente_id, Factura.enviada_el.isnot(None))
    return select.where(false())


def cliente_o_404(id):
    cliente = db.session.scalar(filtrar_clientes(db.select(Cliente).filter_by(id=id)))
    if cliente is None:
        # 404 y no 403 a propósito: no confirmamos que ese cliente exista.
        abort(404)
    return cliente


def pedido_o_404(id):
    pedido = db.session.scalar(filtrar_pedidos(db.select(Pedido).filter_by(id=id)))
    if pedido is None:
        abort(404)
    return pedido
