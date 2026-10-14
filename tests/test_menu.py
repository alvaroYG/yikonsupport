"""Menú lateral por secciones plegables (app/navegacion.py)."""
from app.models import User
from app.extensions import db
from app.navegacion import menu_lateral
from tests.conftest import login


def _menu(email, endpoint="main.inicio", blueprint="main", avisos=None):
    u = db.session.scalar(db.select(User).filter_by(email=f"{email.lower()}@ejemplo.com"))
    return {s["clave"]: s for s in menu_lateral(u, endpoint, blueprint, avisos)}


def test_cada_rol_ve_sus_secciones(app):
    assert list(_menu("admin")) == ["pedidos", "catalogo", "clientes", "soporte", "equipo", "admin"]
    assert list(_menu("ofi")) == ["pedidos", "catalogo", "clientes", "equipo"]        # sin tickets ni administración
    assert [e["endpoint"] for e in _menu("ofi")["clientes"]["enlaces"]] == ["facturas.lista"]   # sin Clientes
    assert "inventario.lista" not in [e["endpoint"] for e in _menu("loga")["catalogo"]["enlaces"]]
    assert list(_menu("sop")) == ["soporte", "equipo"]
    assert list(_menu("chrA")) == ["soporte"]


def test_la_seccion_de_la_pagina_actual_va_abierta(app):
    m = _menu("admin", "productos.editar_kit", "productos")
    assert m["catalogo"]["abierta"] and not m["pedidos"]["abierta"]
    activos = [e["endpoint"] for s in m.values() for e in s["enlaces"] if e["activo"]]
    assert activos == ["productos.kits"]                 # editar un kit marca "Kits", no "Productos"
    m = _menu("admin", "pedidos.preparar_pedido", "pedidos")
    assert [e["endpoint"] for e in m["pedidos"]["enlaces"] if e["activo"]] == ["pedidos.preparar"]
    m = _menu("admin", "admin.editar_usuario", "admin")
    assert m["admin"]["abierta"] and [e["endpoint"] for e in m["admin"]["enlaces"] if e["activo"]] == ["admin.usuarios"]


def test_una_seccion_de_un_solo_enlace_va_directa_y_los_avisos_suben_a_la_cabecera(app):
    m = _menu("sop", "soporte.lista", "soporte", {"soporte": 3})
    assert m["soporte"]["directo"] and m["soporte"]["enlaces"][0]["contador"] == 3
    m = _menu("admin", avisos={"mensajes": 2, "internos": 1, "validar": 4})
    assert not m["pedidos"]["directo"] and m["pedidos"]["contador"] == 7     # sección cerrada: 3 + 4 en la cabecera


def test_html_del_menu(app, client):
    login(client, "admin")
    html = client.get("/productos/kits").get_data(as_text=True)
    assert 'id="menu-catalogo"' in html and 'class="collapse show" id="menu-catalogo"' in html
    assert 'class="collapse " id="menu-pedidos"' in html                      # las demás, cerradas
    assert 'data-bs-target="#menu-pedidos"' in html                          # cabecera = botón plegable
