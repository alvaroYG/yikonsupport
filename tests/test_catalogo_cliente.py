"""Catálogo propio de cada cliente: qué kits puede pedir y qué productos ve (app/catalogo_cliente.py)."""
import json

from app.extensions import db
from app.models import Cliente, ComponenteKit, Kit, Pedido, Producto, RegistroAuditoria
from conftest import contenido, login, pedido_cliente


def _segundo_kit():
    p2 = Producto(referencia="P2", nombre="Tubos", precio=10)
    k2 = Kit(referencia="K2", nombre="Kit dos", precio=50, cerrado=False, componentes=[ComponenteKit(producto=p2, cantidad=1)])
    db.session.add_all([p2, k2])
    db.session.commit()
    return k2, p2


def _guardar(client, modo="propio", kits=(), productos=()):
    return client.post("/clientes/1/catalogo", data={"modo": modo, "kit": list(kits), "producto": list(productos),
                                                     "accion": "guardar"}, follow_redirects=True)


def test_por_defecto_todo_y_con_catalogo_propio_solo_lo_marcado(app, client):
    k2, p2 = _segundo_kit()
    login(client, "cliA")
    html = client.get("/productos/catalogo").get_data(as_text=True)
    assert "Kit uno" in html and "Kit dos" in html                    # de entrada, todo
    client.post("/auth/logout")
    login(client, "loga")                                             # su Soporte de cliente
    assert "Su catálogo" in client.get("/clientes/1").get_data(as_text=True)
    r = _guardar(client, kits=[k2.id], productos=[p2.id])
    assert "Catálogo guardado" in r.get_data(as_text=True)
    assert db.session.get(Cliente, 1).catalogo_propio
    assert db.session.scalar(db.select(RegistroAuditoria).where(RegistroAuditoria.detalle.like("catálogo: solo lo marcado%")))
    client.post("/auth/logout")
    login(client, "cliA")
    html = client.get("/productos/catalogo").get_data(as_text=True)
    assert "Kit dos" in html and "Kit uno" not in html and "Tubos" in html
    # En la ventana de pedido solo sale su kit...
    html = client.get("/pedidos/nuevo").get_data(as_text=True)
    atributo = html.split('data-catalogo="', 1)[1].split('"', 1)[0]
    assert "Kit dos" in atributo and "Kit uno" not in atributo
    # ...y pedir uno que no está, por mucho que se fuerce, no se puede
    r = client.post("/pedidos/nuevo", data={"contenido": contenido([(1, 1, {1: 1})]), "fecha": "2026-09-25", "referencia": "OC-X"})
    assert "no está en su catálogo" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count(Pedido.id))) == 0
    client.post("/pedidos/nuevo", data={"contenido": contenido([(k2.id, 1, {p2.id: 1})]), "fecha": "2026-09-25", "referencia": "OC-Y"})
    assert db.session.scalar(db.select(db.func.count(Pedido.id))) == 1
    # El otro cliente sigue viéndolo todo
    client.post("/auth/logout")
    login(client, "cliB")
    assert "Kit uno" in client.get("/productos/catalogo").get_data(as_text=True)


def test_yikon_puede_pedir_cualquier_cosa_en_su_nombre(app, client):
    k2, p2 = _segundo_kit()
    login(client, "admin")
    _guardar(client, kits=[k2.id])
    r = client.post("/pedidos/nuevo", data={"cliente_id": 1, "contenido": contenido([(1, 1, {1: 1})]),
                                            "fecha": "2026-09-25", "referencia": "OC-Z"})
    assert r.status_code == 302 and db.session.scalar(db.select(db.func.count(Pedido.id))) == 1


def test_avisa_si_quita_un_kit_de_una_proforma_abierta_y_copiar_de_otro(app, client):
    k2, p2 = _segundo_kit()
    login(client, "cliA")
    pedido_cliente(client, con_proforma=True)                         # proforma solicitada con Kit uno
    client.post("/auth/logout")
    login(client, "admin")
    r = _guardar(client, kits=[k2.id])
    assert "proformas abiertas con kits que ya no están" in r.get_data(as_text=True)
    # Copiar el de A a B
    r = client.post("/clientes/2/catalogo", data={"accion": "copiar", "copiar_de": 1}, follow_redirects=True)
    assert "Copiado el catálogo de Clínica A" in r.get_data(as_text=True)
    b = db.session.get(Cliente, 2)
    assert b.catalogo_propio and [k.id for k in b.kits_catalogo] == [k2.id]
    # Volver a "todo" lo vuelve a abrir
    _guardar(client, modo="todo")
    assert not db.session.get(Cliente, 1).catalogo_propio


def test_permisos(app, client):
    login(client, "logb")                                             # Soporte de otro cliente
    assert client.post("/clientes/1/catalogo", data={"modo": "todo"}).status_code == 404
    client.post("/auth/logout")
    login(client, "ofi")
    assert client.post("/clientes/1/catalogo", data={"modo": "todo"}).status_code == 403
