"""Historial del pedido, repetir pedido, pedido interno en un paso y estadísticas."""
import json
import re

from app.extensions import db
from app.models import Pedido
from tests.conftest import doc_pedido, contenido, llevar_a_validado, login, pedido_cliente


def _pedido_con_historia(client):
    login(client, "cliA"); pedido_cliente(client, cantidad=2); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    llevar_a_validado(client, p.id)
    return p


def test_historial_completo_para_logistics(app, client):
    p = _pedido_con_historia(client)
    login(client, "loga")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    for paso in ["Pedido creado", "En preparación", "Pendiente de validación", "Listo para enviar", "foto(s) subida(s)"]:
        assert paso in html
    assert "loga" in html                                   # quién lo hizo


def test_historial_simplificado_para_el_cliente(app, client):
    p = _pedido_con_historia(client)
    login(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    bloque = html[html.index('class="historial"'):]
    bloque = bloque[:bloque.index("</ol>")]
    assert "Pedido creado" in bloque and bloque.count("En preparación") == 1   # los pasos internos, agrupados
    assert "Listo para enviar" not in bloque and "foto" not in bloque and "loga" not in bloque


def test_repetir_pedido(app, client):
    login(client, "cliA"); pedido_cliente(client, cantidad=3)
    p = db.session.scalar(db.select(Pedido))
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    datos = re.search(r'data-repetir="([^"]+)"', html).group(1).replace("&#34;", '"')
    assert json.loads(datos)["kits"] == [{"kit_id": 1, "cantidad": 3, "productos": [{"producto_id": 1, "cantidad": 3}]}]
    # sin JavaScript: /pedidos/nuevo?repetir=ID sale ya relleno
    html = client.get(f"/pedidos/nuevo?repetir={p.id}").get_data(as_text=True)
    oculto = re.search(r'name="contenido" type="hidden" value="([^"]*)"', html).group(1).replace("&#34;", '"')
    assert json.loads(oculto)["kits"] == [{"kit_id": 1, "cantidad": 3, "productos": [{"producto_id": 1, "cantidad": 3}]}]
    # no se puede "repetir" un pedido de otra empresa
    client.post("/auth/logout"); login(client, "cliB")
    assert client.get(f"/pedidos/nuevo?repetir={p.id}").status_code == 404


def test_pedido_interno_exige_cliente_y_productos(app, client):
    login(client, "loga")
    r = client.post("/pedidos/nuevo", data={"uso": "ruo", "documento": doc_pedido(), "cliente_id": 0, "fecha": "2026-09-01"})
    html = r.get_data(as_text=True)
    assert "Elige el cliente." in html and "Añade al menos un kit" in html
    # logistics no puede crear pedidos para un cliente que no es suyo
    client.post("/pedidos/nuevo", data={"uso": "ruo", "documento": doc_pedido(), "cliente_id": 2, "fecha": "2026-09-01",
                                        "contenido": contenido(sueltos={1: 1})})
    assert db.session.scalar(db.select(db.func.count(Pedido.id))) == 0


def test_estadisticas_solo_admin(app, client):
    login(client, "cliA"); pedido_cliente(client, cantidad=2); client.post("/auth/logout")
    login(client, "admin")
    html = client.get("/estadisticas").get_data(as_text=True)
    assert "Pedidos por mes" in html and "Clínica A" in html and "242,00 €" in html
    assert client.get("/estadisticas?meses=24").status_code == 200
    for usuario in ("loga", "cliA"):
        client.post("/auth/logout"); login(client, usuario)
        assert client.get("/estadisticas").status_code == 403
