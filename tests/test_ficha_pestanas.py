"""15/10/2026 · Ficha del pedido en pestañas (Contenido y lotes · Proforma · Fotos · Facturas;
las pinta js/ficha_pedido.js) y barra «Lo que toca» abajo (pedidos/_lo_que_toca.html):
el siguiente paso para quien mira. Escenario de conftest: ofi = Almacén · fac = Facturación ·
loga = Soporte de cliente (FAS) de Clínica A · cliA = su cliente."""
import re

from app.extensions import db
from app.models import Pedido
from tests.conftest import login, pedido_cliente, subir_foto


def _salir(client):
    client.post("/auth/logout")


def _pedido(client, con_proforma=False):
    login(client, "cliA"); pedido_cliente(client, con_proforma=con_proforma); _salir(client)
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def _barra(html):
    """El HTML de la barra «Lo que toca» ('' si no sale)."""
    m = re.search(r'<div class="lo-que-toca".*?</div>\s*</div>\s*</div>', html, re.S)
    return m.group(0) if m else ""


def test_la_ficha_tiene_las_pestanas_y_los_botones_con_nombre(app, client):
    p = _pedido(client)
    login(client, "admin")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "data-pestanas" in html
    for clave in ("pedido", "proforma", "fotos", "facturas"):
        assert f'id="pestana-{clave}"' in html
    # El historial va a la derecha, con los documentos (fuera de las pestañas)
    lateral = html.split('class="ficha-lateral"')[1]
    assert 'id="documentos"' in lateral and 'id="historial"' in lateral
    # Las secciones siguen dentro (sin JavaScript se ve todo, como antes) y con sus ids (#lotes…)
    assert 'id="contenido"' in html and 'id="lotes"' in html
    assert "btn-secciones" not in html and "Abrir todo" not in html
    assert ">Cambiar estado</button>" in html.replace("\n", "")


def test_almacen_empieza_la_preparacion_desde_la_barra(app, client):
    p = _pedido(client)
    login(client, "ofi")
    barra = _barra(client.get(f"/pedidos/{p.id}").get_data(as_text=True))
    assert "Aceptado: listo para empezar a prepararlo" in barra
    assert f'action="/pedidos/{p.id}/preparacion"' in barra
    client.post(f"/pedidos/{p.id}/preparacion")
    assert db.session.get(Pedido, p.id).estado == "en_preparacion"
    barra = _barra(client.get(f"/pedidos/{p.id}").get_data(as_text=True))
    assert "Haz las fotos y mándalo a validar" in barra and 'data-pestana-inicial="fotos"' in barra
    subir_foto(client, p.id)
    barra = _barra(client.get(f"/pedidos/{p.id}").get_data(as_text=True))
    assert f'action="/pedidos/{p.id}/enviar-validacion"' in barra


def test_el_soporte_valida_desde_la_barra(app, client):
    p = _pedido(client)
    login(client, "ofi"); client.post(f"/pedidos/{p.id}/preparacion"); subir_foto(client, p.id)
    client.post(f"/pedidos/{p.id}/enviar-validacion"); _salir(client)
    login(client, "loga")
    barra = _barra(client.get(f"/pedidos/{p.id}").get_data(as_text=True))
    assert "Revisa las fotos" in barra and 'data-enfocar="#' in barra
    assert 'data-pestana="fotos" data-aviso="por validar"' in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Normalmente valida" not in barra                      # (eso es para admin)
    client.post(f"/pedidos/{p.id}/validar", data={"aprobar": "1"})   # lo que manda el botón de la barra
    assert db.session.get(Pedido, p.id).estado == "validado"
    _salir(client)
    login(client, "ofi")                                          # y a Almacén le toca enviarlo
    barra = _barra(client.get(f"/pedidos/{p.id}").get_data(as_text=True))
    assert "Validado: listo para enviar" in barra and 'data-estado-destino="enviado"' in barra


def test_facturacion_va_a_la_proforma_y_el_cliente_la_responde(app, client):
    p = _pedido(client, con_proforma=True)
    login(client, "fac")
    barra = _barra(client.get(f"/pedidos/{p.id}").get_data(as_text=True))
    assert "Prepara y envía la proforma" in barra and 'data-pestana-inicial="proforma"' in barra
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert 'data-pestana="proforma" data-aviso="por enviar"' in html and 'data-pestana="fotos" data-aviso=""' in html
    _salir(client)
    login(client, "ofi")                                          # Almacén no ve las proformas
    assert client.get(f"/pedidos/{p.id}").status_code == 404


def test_el_cliente_confirma_la_recepcion_en_la_barra_y_yikon_en_la_cabecera(app, client):
    p = _pedido(client)
    p.estado = "enviado"
    db.session.commit()
    login(client, "cliA")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Confírmenos que lo ha recibido" in _barra(html)
    _salir(client)
    login(client, "admin")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Confírmenos" not in html
    assert f'action="/pedidos/{p.id}/recibido"' in html.split('id="acciones-pedido"')[1].split("</div>")[0]


def test_sin_nada_que_hacer_no_sale_la_barra(app, client):
    p = _pedido(client)
    login(client, "cliA")                                         # aceptado: le toca a Yikon
    assert 'class="lo-que-toca"' not in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
