from app.extensions import db
from app.models import Cliente, Producto
from tests.conftest import doc_pedido, ref, contenido, login, pedido_cliente


def _preparar(client):
    """YK-<año>-CLA-1 (Kit 1, 2026-09-01), CLA-2 (Kit 2, 2026-09-20), CLB-1 (Kit 1)."""
    from app.models import ComponenteKit, Kit
    p2 = Producto(referencia="P2", nombre="Kit 2", precio=50)
    db.session.add(Kit(referencia="K2", nombre="Kit dos", precio=50, componentes=[ComponenteKit(producto=p2, cantidad=1)]))
    db.session.commit()
    login(client, "cliA")
    client.post("/pedidos/nuevo", data={"documento": doc_pedido(), "contenido": contenido([(1, 1, {1: 1})]), "fecha": "2026-09-01", "referencia": "R1"})
    client.post("/pedidos/nuevo", data={"documento": doc_pedido(), "contenido": contenido([(2, 2, {2: 2})]), "fecha": "2026-09-20", "referencia": "R2"})
    client.post("/auth/logout")
    login(client, "cliB"); pedido_cliente(client); client.post("/auth/logout")


def _refs(html):
    return [r for r in [ref("CLA", 1), ref("CLA", 2), ref("CLB", 1)] if r in html]


def test_filtros_por_columna(app, client):
    _preparar(client)
    login(client, "admin")
    b = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica B"))
    assert _refs(client.get("/pedidos/").text) == [ref("CLA", 1), ref("CLA", 2), ref("CLB", 1)]
    assert _refs(client.get(f"/pedidos/?cliente_id={b.id}").text) == [ref("CLB", 1)]
    assert _refs(client.get("/pedidos/?producto_id=2").text) == [ref("CLA", 2)]
    assert _refs(client.get("/pedidos/?desde=2026-09-10&hasta=2026-09-21").text) == [ref("CLA", 2)]
    assert _refs(client.get("/pedidos/?q=cla-").text) == [ref("CLA", 1), ref("CLA", 2)]
    assert _refs(client.get("/pedidos/?desde=esto-no-es-fecha").text) == [ref("CLA", 1), ref("CLA", 2), ref("CLB", 1)]


def test_filtros_no_saltan_el_alcance(app, client):
    _preparar(client)
    login(client, "cliA")
    b = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica B"))
    # un cliente que filtra por OTRA empresa en la URL no ve nada de ella
    assert _refs(client.get(f"/pedidos/?cliente_id={b.id}").text) == []


def test_exportar_pdf(app, client):
    _preparar(client)
    login(client, "admin")
    r = client.get("/pedidos/exportar.pdf?producto_id=2")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    assert r.data.startswith(b"%PDF")


def test_todos_exportan_pero_solo_lo_suyo(app, client):
    _preparar(client)
    for usuario in ["admin", "loga", "cliA"]:
        login(client, usuario)
        assert client.get("/pedidos/exportar.pdf").status_code == 200
        client.post("/auth/logout")
    # el PDF pasa por el mismo alcance: cliA no puede exportar pedidos de la Clínica B
    login(client, "cliA")
    b = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica B"))
    from app.pedidos.routes import _pedidos_filtrados
    with app.test_request_context(f"/pedidos/?cliente_id={b.id}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com")))
        select, _, _ = _pedidos_filtrados()
        assert db.session.scalars(select).all() == []
