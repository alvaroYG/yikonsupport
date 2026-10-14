"""Capa 2: de lo que puede ver, CUÁLES registros. Aquí se intenta 'colarse'."""
from app.extensions import db
from app.models import Cliente, Pedido
from tests.conftest import ref, login, pedido_cliente


def _pedido_de(app, cliente_nombre):
    return db.session.scalar(db.select(Pedido).join(Cliente).filter(Cliente.nombre == cliente_nombre))


def test_cliente_solo_ve_pedidos_de_su_empresa(app, client):
    login(client, "cliB"); pedido_cliente(client); client.post("/auth/logout")
    login(client, "cliA"); pedido_cliente(client)
    pedido_b = _pedido_de(app, "Clínica B")
    html = client.get("/pedidos/").get_data(as_text=True)
    assert ref("CLA", 1) in html and ref("CLB", 1) not in html
    # cambiar el número en la URL no sirve: 404, ni siquiera confirma que exista
    assert client.get(f"/pedidos/{pedido_b.id}").status_code == 404


def test_logistics_solo_ve_sus_clientes(app, client):
    login(client, "cliB"); pedido_cliente(client); client.post("/auth/logout")
    login(client, "loga")
    b = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica B"))
    assert "Clínica B" not in client.get("/clientes/").get_data(as_text=True)
    assert client.get(f"/clientes/{b.id}").status_code == 404
    assert client.get(f"/pedidos/{_pedido_de(app, 'Clínica B').id}").status_code == 404
    # ni puede cambiarle el estado a un pedido ajeno
    r = client.post(f"/pedidos/{_pedido_de(app, 'Clínica B').id}/estado", data={"estado": "cancelado"})
    assert r.status_code == 404


def test_logistics_no_crea_pedidos_para_clientes_ajenos(app, client):
    login(client, "loga")
    b = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica B"))
    client.post("/pedidos/nuevo", data={"cliente_id": b.id, "fecha": "2026-09-25"})
    assert db.session.scalar(db.select(db.func.count(Pedido.id))) == 0


def test_logistics_con_varios_clientes(app, client):
    from app.models import User
    loga = db.session.scalar(db.select(User).filter_by(email="loga@ejemplo.com"))
    loga.clientes_asignados.append(db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica B")))
    db.session.commit()
    login(client, "loga")
    html = client.get("/clientes/").get_data(as_text=True)
    assert "Clínica A" in html and "Clínica B" in html


def test_cliente_no_ve_importes(app, client):
    login(client, "cliA"); pedido_cliente(client, cantidad=3)
    pedido = _pedido_de(app, "Clínica A")
    html = client.get(f"/pedidos/{pedido.id}").get_data(as_text=True)
    assert "Kit 1" in html and "€" not in html
