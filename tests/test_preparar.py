"""Vista de móvil "Preparar": lista de pedidos por preparar, fotos y envío a validación."""
from io import BytesIO

from app.extensions import db
from app.models import FotoPedido, Pedido
from tests.conftest import FOTO_JPG, login, pedido_cliente


def _pedido_confirmado(client):
    login(client, "cliA"); pedido_cliente(client, cantidad=2); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    return p


def _foto(client, p):
    return client.post(f"/pedidos/{p.id}/fotos", content_type="multipart/form-data",
                       data={"fotos": (BytesIO(FOTO_JPG), "caja.jpg"), "volver": "preparar"})


def test_lista_y_permisos(app, client):
    p = _pedido_confirmado(client)
    login(client, "admin")
    html = client.get("/pedidos/preparar").get_data(as_text=True)
    assert p.referencia_interna in html and "vista-movil" in html
    client.post("/auth/logout")
    for usuario in ("loga", "cliA"):
        login(client, usuario)
        assert client.get("/pedidos/preparar").status_code == 403
        assert client.get(f"/pedidos/{p.id}/preparar").status_code == 403
        client.post("/auth/logout")


def test_ficha_muestra_contenido_y_lotes(app, client):
    login(client, "admin")
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 10,
                                                 "lote": "LOTE-ABC", "caducidad": "2099-12-31"})
    client.post("/auth/logout")
    p = _pedido_confirmado(client)
    login(client, "admin")
    html = client.get(f"/pedidos/{p.id}/preparar").get_data(as_text=True)
    assert "LOTE-ABC" in html and 'capture="environment"' in html
    assert "€" not in html                                   # sin precios


def test_fotos_y_enviar_desde_el_movil(app, client):
    p = _pedido_confirmado(client)
    login(client, "admin")
    # sin fotos no se puede enviar
    client.post(f"/pedidos/{p.id}/enviar-validacion", data={"volver": "preparar"})
    assert db.session.get(Pedido, p.id).estado == "en_preparacion"
    r = _foto(client, p)
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/pedidos/{p.id}/preparar")
    foto = db.session.scalar(db.select(FotoPedido))
    r = client.post(f"/pedidos/{p.id}/fotos/{foto.id}/borrar", data={"volver": "preparar"})
    assert r.headers["Location"].endswith(f"/pedidos/{p.id}/preparar")
    assert db.session.scalar(db.select(db.func.count(FotoPedido.id))) == 0
    _foto(client, p)
    r = client.post(f"/pedidos/{p.id}/enviar-validacion", data={"volver": "preparar"})
    assert r.headers["Location"].endswith("/pedidos/preparar")      # a por el siguiente
    assert db.session.get(Pedido, p.id).estado == "en_validacion"
    # ya no sale en la lista y su ficha móvil lo dice
    assert p.referencia_interna not in client.get("/pedidos/preparar").get_data(as_text=True)
    assert "ya no está en preparación" in client.get(f"/pedidos/{p.id}/preparar").get_data(as_text=True)


def test_desde_la_ficha_normal_sigue_volviendo_a_la_ficha(app, client):
    p = _pedido_confirmado(client)
    login(client, "admin")
    r = client.post(f"/pedidos/{p.id}/fotos", content_type="multipart/form-data",
                    data={"fotos": (BytesIO(FOTO_JPG), "caja.jpg")})
    assert r.headers["Location"].endswith(f"/pedidos/{p.id}")


def test_aceptado_se_empieza_desde_el_movil(app, client):
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    assert p.estado == "aceptado"
    login(client, "admin")
    assert p.referencia_interna in client.get("/pedidos/preparar").get_data(as_text=True)
    html = client.get(f"/pedidos/{p.id}/preparar").get_data(as_text=True)
    assert "Empezar preparación" in html and 'capture="environment"' not in html    # aún sin fotos
    r = client.post(f"/pedidos/{p.id}/preparacion", data={"volver": "preparar"})
    assert r.headers["Location"].endswith(f"/pedidos/{p.id}/preparar")
    assert db.session.get(Pedido, p.id).estado == "en_preparacion"
    assert 'capture="environment"' in client.get(f"/pedidos/{p.id}/preparar").get_data(as_text=True)


def test_los_lotes_salen_debajo_de_cada_fila_sin_duplicar(app, client):
    """15/10 (cambio de Álvaro en preparar.html): el lote, la cantidad y la caducidad, debajo de cada
    kit o producto de «Qué lleva». Si el mismo producto va en un kit y suelto, las unidades
    reservadas se reparten entre las filas (no se repiten)."""
    from tests.conftest import contenido, doc_pedido, proforma_aceptada
    login(client, "admin")
    client.post("/inventario/movimiento", data={"producto_id": 1, "tipo": "entrada", "cantidad": 10,
                                                "lote": "L-MIXTO", "caducidad": "2099-12-31"})
    client.post("/auth/logout")
    login(client, "cliA")
    client.post("/pedidos/nuevo", data={"contenido": contenido([(1, 1, {1: 1})], sueltos={1: 2}),
                                        "fecha": "2026-09-25", "referencia": "OC-MIXTO", "documento": doc_pedido()})
    proforma_aceptada()
    client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    login(client, "admin")
    html = client.get(f"/pedidos/{p.id}/preparar").get_data(as_text=True)
    assert html.count('L-MIXTO</span> × <strong>1</strong>') == 1      # la fila del kit
    assert html.count('L-MIXTO</span> × <strong>2</strong>') == 1      # la del suelto
    assert "Pendiente de reservar" not in html
