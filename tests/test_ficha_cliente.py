"""Ficha del cliente (Yikon): franja con los datos principales y el resto en pestañas."""
import re

from conftest import login


def _pestanas(html):
    return re.findall(r'data-bs-target="#pestana-(\w+)"', html)


def test_admin_ve_las_seis_pestanas_y_se_abre_en_pedidos(app, client):
    login(client, "admin")
    html = client.get("/clientes/1").get_data(as_text=True)
    assert _pestanas(html) == ["pedidos", "envio", "facturacion", "precios", "catalogo", "avisos"]
    assert 'class="tab-pane show active" id="pestana-pedidos"' in html
    # los datos principales arriba y el interruptor de precios una sola vez (no hay dos formularios iguales)
    assert "Ver datos completos" in html and html.count("clientes/1/ver-precios") == 1
    # las anclas de siempre siguen existiendo dentro de sus pestañas (redirecciones, paginación)
    for ancla in ("pedidos", "facturas", "facturacion", "precios", "catalogo", "avisos"):
        assert f'id="{ancla}"' in html, ancla


def test_su_soporte_de_cliente_tambien_y_otro_no_la_ve(app, client):
    login(client, "loga")
    html = client.get("/clientes/1").get_data(as_text=True)
    assert _pestanas(html) == ["pedidos", "envio", "facturacion", "precios", "catalogo", "avisos"]
    client.post("/auth/logout")
    login(client, "logb")                      # Soporte de otro cliente
    assert client.get("/clientes/1").status_code == 404
