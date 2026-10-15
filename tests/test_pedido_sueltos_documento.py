"""14/10/2026 · Lo que se había perdido de los cambios de ChatGPT (9/10), recuperado:
- el cliente también pide productos sueltos (con catálogo propio, solo los de su catálogo);
- el documento del pedido es obligatorio para todos (cliente y Yikon);
- desplegables con buscador (data-buscable, static/js/selectores_buscables.js)."""
import json

from app.extensions import db
from app.models import Cliente, Kit, Pedido, Producto
from tests.conftest import contenido, doc_pedido, login


def _productos():
    a = Producto(referencia="SUELTO-A", nombre="Buffer suelto", precio=10)
    b = Producto(referencia="SUELTO-B", nombre="Tubos sueltos", precio=5)
    db.session.add_all([a, b])
    db.session.commit()
    return a, b


def _pide(client, sueltos=None, kits=((1, 1, {1: 1}),), documento=True, **extra):
    datos = {"contenido": contenido(list(kits), sueltos), "fecha": "2026-10-14", "referencia": "OC-S",
             "uso": "ruo", **extra}
    if documento:
        datos["documento"] = doc_pedido()
    return client.post("/pedidos/nuevo", data=datos, content_type="multipart/form-data")


def _productos_de_la_ventana(html):
    """Los productos que ofrece la ventana de pedido para los sueltos (atributo data-productos)."""
    import html as h
    import re
    return [p["texto"] for p in json.loads(h.unescape(re.search(r'data-productos="([^"]*)"', html).group(1)))]


def test_el_documento_es_obligatorio_para_el_cliente_y_para_yikon(app, client):
    login(client, "cliA")
    r = _pide(client, documento=False)
    assert r.status_code == 200 and "El documento de pedido es obligatorio." in r.get_data(as_text=True)
    assert db.session.scalar(db.select(Pedido)) is None
    client.post("/auth/logout")
    login(client, "loga")
    r = _pide(client, documento=False, cliente_id=1)
    assert "El documento de pedido es obligatorio." in r.get_data(as_text=True)
    assert db.session.scalar(db.select(Pedido)) is None
    assert _pide(client, cliente_id=1, referencia="").status_code == 302          # con documento, sí
    pedido = db.session.scalar(db.select(Pedido))
    assert [d.nombre_original for d in pedido.documentos] == ["pedido.pdf"]
    # La ventana lo marca como obligatorio y trae el aviso para el navegador
    html = client.get("/pedidos/nuevo").get_data(as_text=True)
    assert 'data-error-documento' in html and 'name="documento"' in html and "required" in html.split('name="documento"')[1][:400]


def test_el_cliente_pide_productos_sueltos_solos_o_con_kits(app, client):
    a, b = _productos()
    login(client, "cliA")
    html = client.get("/pedidos/nuevo").get_data(as_text=True)
    assert "Productos sueltos" in html and "data-anadir-suelto" in html
    assert "SUELTO-A — Buffer suelto" in _productos_de_la_ventana(html)        # sin catálogo propio: todos
    assert _pide(client, sueltos={a.id: 3}, kits=()).status_code == 302          # solo sueltos, sin kit
    pedido = db.session.scalar(db.select(Pedido))
    assert [(l.producto_id, l.cantidad) for l in pedido.lineas_sueltas] == [(a.id, 3)] and not pedido.kits
    r = _pide(client, sueltos={b.id: 1}, referencia="OC-S2")                     # con un kit
    assert r.status_code == 302
    r = _pide(client, kits=(), referencia="OC-S3")                               # nada de nada
    assert "Añade al menos un kit o un producto." in r.get_data(as_text=True)


def test_con_catalogo_propio_solo_los_productos_de_su_catalogo(app, client):
    a, b = _productos()
    cliente = db.session.get(Cliente, 1)
    cliente.catalogo_propio = True
    cliente.kits_catalogo = [db.session.get(Kit, 1)]
    cliente.productos_catalogo = [a]
    db.session.commit()
    login(client, "cliA")
    ofrecidos = _productos_de_la_ventana(client.get("/pedidos/nuevo").get_data(as_text=True))
    assert ofrecidos == ["SUELTO-A — Buffer suelto"]
    r = _pide(client, sueltos={b.id: 1})
    assert "El producto Tubos sueltos no está en su catálogo" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(Pedido)) is None
    assert _pide(client, sueltos={a.id: 2}).status_code == 302
    # Yikon, en nombre del cliente, puede añadir cualquier cosa
    client.post("/auth/logout"); login(client, "loga")
    assert _pide(client, sueltos={b.id: 1}, cliente_id=1, referencia="OC-YK").status_code == 302


def test_repetir_conserva_los_sueltos_del_cliente_que_puede_pedir(app, client):
    a, b = _productos()
    login(client, "cliA")
    _pide(client, sueltos={a.id: 2, b.id: 1})
    pedido = db.session.scalar(db.select(Pedido))
    html = client.get(f"/pedidos/nuevo?repetir={pedido.id}").get_data(as_text=True)
    assert f'&#34;producto_id&#34;: {a.id}' in html and f'&#34;producto_id&#34;: {b.id}' in html
    # Si después le ponen catálogo propio sin B, al repetir B ya no sale
    cliente = db.session.get(Cliente, 1)
    cliente.catalogo_propio, cliente.kits_catalogo, cliente.productos_catalogo = True, [db.session.get(Kit, 1)], [a]
    db.session.commit()
    html = client.get(f"/pedidos/nuevo?repetir={pedido.id}").get_data(as_text=True)
    sueltos = html.split("sueltos")[-1] if "sueltos" in html else ""
    assert f'&#34;producto_id&#34;: {a.id}, &#34;cantidad&#34;: 2' in html
    assert f'&#34;producto_id&#34;: {b.id}, &#34;cantidad&#34;: 1' not in html and sueltos is not None


def test_desplegables_con_buscador(app, client):
    login(client, "admin")
    html = client.get("/pedidos/nuevo").get_data(as_text=True)
    assert "js/selectores_buscables.js" in html
    assert 'name="cliente_id"' in html and 'data-buscable="Buscar cliente"' in html
    assert 'data-txt-buscar-kit="Buscar kit por nombre o referencia"' in html
    html = client.get("/productos/kits/nuevo").get_data(as_text=True)
    assert 'data-buscable="Buscar producto por nombre o referencia"' in html
    # Ampliar un pedido abierto (ficha): kit y producto con buscador
    _pide(client, cliente_id=1, referencia="OC-AMP")
    pedido = db.session.scalar(db.select(Pedido))
    html = client.get(f"/pedidos/{pedido.id}").get_data(as_text=True)
    assert 'data-buscable="Buscar kit por nombre o referencia"' in html or 'name="kit_id"' not in html
    assert 'data-buscable="Buscar producto por nombre o referencia"' in html
