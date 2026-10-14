"""Opción por cliente: sus usuarios ven (o no) los precios en la plataforma."""
from datetime import date

from app.models import ahora  # facturas ya enviadas al cliente (las ve)
from app.extensions import db
from app.models import Cliente, Factura, Pedido
from tests.conftest import login, pedido_cliente


def test_por_defecto_el_cliente_no_ve_precios(app, client):
    login(client, "cliA"); pedido_cliente(client)
    p = db.session.scalar(db.select(Pedido))
    for url in ["/", "/pedidos/", f"/pedidos/{p.id}"]:
        assert "100,00 €" not in client.get(url).get_data(as_text=True), url


def test_logistics_lo_activa_y_el_cliente_ve_sus_precios(app, client):
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    db.session.add(Factura(enviada_el=ahora(), numero="F-1", cliente_id=1, pedido=p, fecha_emision=date(2026, 9, 1),
                           base_imponible=100, iva=21, total=121)); db.session.commit()
    login(client, "loga")
    html = client.get("/clientes/").get_data(as_text=True)
    assert "Ve precios" in html
    client.post("/clientes/1/ver-precios", data={"ver_precios": "1", "volver": "lista"})
    assert db.session.get(Cliente, 1).ver_precios
    # logistics no puede tocar clientes que no son suyos
    assert client.post("/clientes/2/ver-precios", data={"ver_precios": "1"}).status_code == 404
    client.post("/auth/logout")
    login(client, "cliA")
    assert "121,00 €" in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "121,00 €" in client.get("/pedidos/").get_data(as_text=True)
    assert "€" not in client.get("/facturas/mias").get_data(as_text=True)     # las facturas, sin importes (están en el PDF)
    # pero sigue sin poder cambiar precios ni ver la ficha de clientes
    assert 'name="precio_kit_' not in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert client.post("/clientes/1/ver-precios", data={"ver_precios": "0"}).status_code == 403
    client.post("/auth/logout")
    login(client, "cliB")                                         # la otra empresa sigue sin precios
    assert "€" not in client.get("/").get_data(as_text=True)
