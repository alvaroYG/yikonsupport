"""
Los roles del 30/09 en el flujo del pedido:
  Almacén (rol "logistica") prepara, hace las fotos y envía, en los pedidos de TODOS los clientes
  desde que se aceptan; el FAS del cliente valida las fotos (solo las de sus clientes). Almacén no
  valida. Desde el 14/10/2026 las proformas y facturas son de Facturación (test_almacen_facturacion.py).
"""
from app.extensions import db
from app.models import Lote, MovimientoInventario, Pedido, Producto
from tests.conftest import doc_pedido, login, pedido_cliente, reservar_lotes, subir_foto


def _pedido_en_preparacion(client, cliente="cliA"):
    login(client, cliente); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    login(client, "ofi")
    client.post(f"/pedidos/{p.id}/preparacion")                   # Logística lo empieza
    return p


def test_logistica_prepara_y_el_fas_valida(app, client):
    p = _pedido_en_preparacion(client, "cliB")                    # de la Clínica B: Logística ve todos
    assert db.session.get(Pedido, p.id).estado == "en_preparacion"
    assert subir_foto(client, p.id).status_code == 302
    client.post(f"/pedidos/{p.id}/enviar-validacion")
    assert db.session.get(Pedido, p.id).estado == "en_validacion"
    # Logística no puede validar su propio trabajo
    assert client.post(f"/pedidos/{p.id}/validar", data={"aprobar": "1"}).status_code == 403
    client.post("/auth/logout")
    # el FAS de otra clínica tampoco (ni lo ve)
    login(client, "loga")
    assert client.post(f"/pedidos/{p.id}/validar", data={"aprobar": "1"}).status_code == 404
    client.post("/auth/logout")
    # el FAS de la Clínica B sí
    login(client, "logb")
    client.post(f"/pedidos/{p.id}/validar", data={"aprobar": "1"})
    assert db.session.get(Pedido, p.id).estado == "validado"
    # y el FAS no envía: eso es de la oficina
    r = client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "transportista": "SEUR",
                                                     "numero_seguimiento": "T1", "confirmar_stock": "1"})
    assert db.session.get(Pedido, p.id).estado == "validado"
    client.post("/auth/logout")
    login(client, "ofi")
    client.post("/inventario/movimiento", data={"articulo": "producto-1", "tipo": "entrada", "cantidad": 5,
                                                "lote": "L1", "caducidad": "2099-12-31"})
    reservar_lotes(client, p.id)             # la oficina (Logística) asigna el lote recién llegado
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "transportista": "SEUR",
                                                 "numero_seguimiento": "T1", "confirmar_stock": "1"})
    assert db.session.get(Pedido, p.id).estado == "enviado"


def test_el_fas_no_prepara_ni_sube_fotos(app, client):
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    login(client, "loga")
    assert client.post(f"/pedidos/{p.id}/preparacion").status_code == 403
    assert client.get("/pedidos/preparar").status_code == 403


def test_logistica_ve_el_chat_interno_y_todos_los_clientes(app, client):
    p = _pedido_en_preparacion(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Chat interno" in html
    client.post(f"/mensajes/pedido/{p.id}/interno", data={"texto": "Falta una caja, la pido hoy"})
    client.post(f"/mensajes/pedido/{p.id}", data={"texto": "Su pedido sale mañana"})   # y con el cliente
    client.post("/auth/logout")
    login(client, "loga")                                             # su FAS ve la nota interna
    assert "Falta una caja" in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    client.post("/auth/logout")
    login(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Su pedido sale mañana" in html and "Falta una caja" not in html


def test_almacen_gestiona_inventario_pero_no_productos_ni_clientes(app, client):
    login(client, "ofi")
    client.post("/inventario/movimiento", data={"articulo": "producto-1", "tipo": "entrada", "cantidad": 5,
                                                "lote": "L-OFI", "caducidad": "2099-12-31"})
    assert db.session.scalar(db.select(Lote).filter_by(codigo="L-OFI")) is not None
    assert db.session.scalar(db.select(db.func.sum(MovimientoInventario.cantidad))) == 5
    assert client.get("/productos/1/editar").status_code == 403          # la ficha es de Facturación...
    client.post("/inventario/producto/1/minimo", data={"stock_minimo": "7"})   # ...el mínimo, desde Inventario
    assert db.session.get(Producto, 1).stock_minimo == 7
    assert client.get("/clientes/1").status_code == 403
    ruta = next(r.rule for r in app.url_map.iter_rules() if r.endpoint == "clientes.cambiar_ver_precios")
    assert client.post(ruta.replace("<int:id>", "1"), data={"ver_precios": "1"}).status_code == 403
    # el nombre del cliente se ve en los pedidos, pero sin enlace a su ficha
    client.post("/auth/logout")
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    login(client, "ofi")
    p = db.session.scalar(db.select(Pedido))
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Clínica A" in html and "/clientes/1\"" not in html


def test_el_fas_ve_la_ficha_de_sus_clientes_y_activa_precios(app, client):
    from app.models import Cliente
    login(client, "loga")
    assert client.get("/clientes/1").status_code == 200
    assert client.get("/clientes/2").status_code == 404
    assert client.get("/inventario/").status_code == 403
    rutas = [r.rule for r in app.url_map.iter_rules() if r.endpoint == "clientes.cambiar_ver_precios"]
    client.post(rutas[0].replace("<int:id>", "1"), data={"ver_precios": "1"})
    assert db.session.get(Cliente, 1).ver_precios


def test_producto_suelto_de_la_oficina(app, client):
    """Facturación crea pedidos para cualquier cliente (con productos sueltos si hace falta). Almacén no."""
    import json
    login(client, "ofi")
    assert client.post("/pedidos/nuevo", data={"uso": "ruo", "cliente_id": 2}).status_code == 403
    client.post("/auth/logout")
    login(client, "fac")
    r = client.post("/pedidos/nuevo", data={"uso": "ruo", "documento": doc_pedido(), 
        "cliente_id": 2, "fecha": "2026-09-30",
        "contenido": json.dumps({"kits": [], "sueltos": [{"producto_id": 1, "cantidad": 2}]})})
    assert r.status_code == 302
    p = db.session.scalar(db.select(Pedido))
    assert p.cliente_id == 2 and p.lineas[0].producto == db.session.get(Producto, 1)
